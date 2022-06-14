#!/bin/bash
# vim: dict+=/usr/share/beakerlib/dictionary.vim cpt=.,w,b,u,t,i,k
. /usr/share/beakerlib/beakerlib.sh || exit 1

### Configuration variables ###

# Git repository with tmt code (origin or fork or own...)
REPO="${REPO:-https://github.com/teemtee/tmt}"

# Branch to checkout code from, if empty then repos' default
BRANCH="${BRANCH:-}"

# Set following to 1 if you are running before release
KEEP_VERSION="${KEEP_VERSION:-0}"

# Skip install if '1' (e.g. plan's prepare has taken care of that)
SKIP_INSTALL="${SKIP_INSTALL:-0}"

# Set to tmt run's `test <options>` command for test filtering
# (including 'tests' subcommand)
TESTS_CMD="${TESTS_CMD:-}"

# Space separated list of plans to execute, empty for all
PLANS="${PLANS:-}"

# Measure coverage: 1 - yes, 0 - no
COVERAGE="${COVERAGE:-0}"

### end of configuration ###

USER="tmt-tester"
USER_HOME="/home/$USER"
USER_COVERAGERC="$USER_HOME/coveragerc"
USER_COVER_DIR=$USER_HOME/Coverage
USER_COVER_FINAL=$USER_COVER_DIR/tmt

CONNECT_RUN="/tmp/CONNECT"

set -o pipefail

TEST_DIR="$(pwd)"

rlJournalStart
    rlPhaseStartSetup

        if [[ $KEEP_VERSION -eq 1 ]]; then
            [[ -z "$BRANCH" ]] && rlDie "Please set BRANCH when running pre-release"
        fi

        if ! rlIsFedora; then
            rlRun "rlImport epel/epel"
            rlRun "dnf config-manager --set-enabled epel"

            for repo in powertools extras crb codeready-builder; do
                real_repo_name="$(dnf repolist --all | grep -Eio "[-a-zA-Z0-9_]*$repo[-a-zA-Z0-9_]*" | head -n1)"
                if [[ -n "$real_repo_name" ]]; then
                    rlRun "dnf config-manager --set-enabled $real_repo_name"
                fi
            done

            #better to install SOME tmt than none (python3-html2text missing on rhel-9)
            SKIP_BROKEN="--skip-broken"

            [[ $COVERAGE -eq 1 ]] && rlRun "dnf install python3-coverage"
        fi

        rlFileBackup /etc/sudoers
        id $USER &>/dev/null && {
            rlRun "pkill -9 -u $USER" 0,1
            rlRun "loginctl terminate-user $USER" 0,1
            rlRun "userdel -r $USER" 0 "Removing existing user"
        }
        rlRun "useradd $USER"
        rlRun "usermod --append --groups libvirt $USER"
        rlRun "echo '$USER ALL=(ALL) NOPASSWD: ALL' >> /etc/sudoers" 0 "password-less sudo for test user"
        rlRun "chmod 400 /etc/sudoers"
        rlRun "loginctl enable-linger $USER" # start session so /run/ directory is initialized

        # Making sure USER can r/w to the /var/tmp/tmt
        test -d /var/tmp/tmt && rlRun "chown $USER:$USER /var/tmp/tmt"

        # Clone repo
        rlRun "git clone $REPO $USER_HOME/tmt"
        rlRun "pushd $USER_HOME/tmt"
        [ -n "$BRANCH" ] && rlRun "git checkout --force '$BRANCH'"
        # Make current commit visible in the log
        rlRun "git show -s | cat"

        # Patch version unless forbidden
        [[ $KEEP_VERSION -ne 1 ]] && rlRun "sed 's/^Version:.*/Version: 9.9.9/' -i tmt.spec"


        if [[ $SKIP_INSTALL -eq 1 ]]; then
            rlLog "Skipping tmt build and install, tmt on the system is \$(rpm -q tmt)"
            # this plan has 'install' when how == full and we have nothing to install
            # easier to create plan from scratch than to delete 'adjust' rule
            cat <<EOF > plans/main.fmf
provision:
  how: local
execute:
  how: tmt
EOF
        else
            # Build tmt packages
            rlRun "dnf builddep -y tmt.spec" 0 "Install build dependencies"
            rlRun "make rpm" || rlDie "Failed to build tmt rpms"

            # From now one we can use tmt (freshly built)
            rlRun "find $USER_HOME/tmt/tmp/RPMS -type f -name '*rpm' | xargs dnf install -y $SKIP_BROKEN"
        fi

        # Make sure that libvirt is running
        rlServiceStart "libvirtd"
        rlRun "su -l -c 'virsh -c qemu:///session list' $USER" || rlDie "qemu:///session not working, no point to continue"

        # Tests need VM machine for 'connect'
        # remove possible leftovers
        test -d $CONNECT_RUN && rlRun "rm -rf $CONNECT_RUN"
        test -d /var/tmp/tmt/testcloud && rlRun "rm -rf /var/tmp/tmt/testcloud"


        # Prepare fedora container image (https://tmt.readthedocs.io/en/latest/questions.html#container-package-cache)
        # but make it work with podman run  registry.fedoraproject.org/fedora:latest
        rlRun "su -l -c 'podman run -itd --name fresh fedora' $USER"
        rlRun "su -l -c 'podman exec fresh dnf makecache' $USER"
        rlRun "su -l -c 'podman commit fresh fresh' $USER"
        rlRun "su -l -c 'podman container rm -f fresh' $USER"
        rlRun "su -l -c 'podman tag fresh registry.fedoraproject.org/fedora:latest' $USER"
        rlRun "su -l -c 'podman images' $USER"

        # Prepare fedora VM
        rlRun "su -l -c 'tmt run --rm plans --default provision -h virtual finish' $USER" 0 "Fetch image"
        # Run dnf makecache in each image (should be single one though)
        for qcow in /var/tmp/tmt/testcloud/images/*qcow2; do
            rlRun "virt-customize -a $qcow --run-command 'dnf makecache'" 0 "pre-fetch dnf cache in the image"
        done

        rlRun "su -l -c 'tmt run --id $CONNECT_RUN plans --default provision -h virtual' $USER"
        CONNECT_TO=$CONNECT_RUN/plans/default/provision/guests.yaml
        rlAssertExists $CONNECT_TO

        # Patch plans/provision/connect.fmf
        CONNECT_FMF=plans/provision/connect.fmf
        echo 'summary: Connect to a running guest' > $CONNECT_FMF
        echo 'provision:' >> $CONNECT_FMF
        sed '/default:/d' $CONNECT_RUN/plans/default/provision/guests.yaml >> $CONNECT_FMF
        rlLog "$(cat $CONNECT_FMF)"

        # Delete the plan -> container vs host are not synced so rpms might not be installable
        rlRun 'rm -f plans/install/minimal.fmf'
        rlRun "git diff | cat"
        if [ -z "$PLANS" ]; then
            rlRun "su -l -c 'cd $USER_HOME/tmt; tmt -c how=full plans ls --filter=enabled:true > $USER_HOME/enabled_plans' $USER"
            PLANS="$(echo $(cat $USER_HOME/enabled_plans))"
        fi

        # Prepend 'tests' to the TESTS_CMD
        if [ -n "$TESTS_CMD" ]; then
          TESTS_CMD="tests $TESTS_CMD"
        fi

        # Coverage setup
        if [[ $COVERAGE -eq 1 ]]; then
            # fix shabang
            rlRun "sed 's;^#!.*;#!/usr/bin/python3;' -i $(command -v tmt)" 0 "Remove -s flag (disables SITECUSTIMIZE)"

            cat <<EOF > $USER_COVERAGERC
[run]
data_file=$USER_COVER_FINAL
parallel=True
source=
    $(dirname $(rpm -ql python3-tmt | grep tmt/base.py$))
    $(command -v tmt)
EOF
            USER_SITE="$(su -l -c 'python3 -m site --user-site' $USER)"
            rlRun "mkdir -p $USER_SITE"
            rlRun "cp $TEST_DIR/sitecustomize.py $USER_SITE"
        fi
            rlRun "chown $USER:$USER -R $USER_HOME"
    rlPhaseEnd

    for plan in $PLANS; do
        rlPhaseStartTest "Test: $plan"
            RUN="run$(echo $plan | tr '/' '-')"
            # unset coverage option
            export COVERAGE_OPT=

            # /plan/install exercise rpm/pip - tmt might be executed in nested vm/container...
            # safer to skip coverage generation instead of trying to make it work
            if [[ $COVERAGE -eq 1 ]] && ! [[ "$plan" =~ /plans/(install|sanity/lint|provision/(virtual|connect)) ]]; then
                # Separate coverage per run
                RUN_COV_RC=$USER_HOME/$RUN.coveragerc
                # keep semicolon at the end
                export COVERAGE_OPT="export COVERAGE_PROCESS_START=$RUN_COV_RC;"
                rlRun "sed 's;data_file=.*;data_file=$USER_COVER_FINAL-$RUN;' $USER_COVERAGERC > $RUN_COV_RC"
            fi

            # Core of the test runs as $USER, -l should clear all BEAKER_envs.
            rlRun "su -l -c 'cd $USER_HOME/tmt; $COVERAGE_OPT \
                tmt -c how=full run -vvv -ddd --id $USER_HOME/$RUN -v plans --name $plan $TESTS_CMD' $USER"

            if [[ -n "$COVERAGE_OPT" ]]; then
                rlRun "su -l -c 'coverage combine --rcfile=$RUN_COV_RC' $USER"
                rlRun "su -l -c 'coverage html -d $USER_HOME/html-report/$RUN --rcfile=$RUN_COV_RC' $USER"
                rlRun "su -l -c 'tar czf $USER_HOME/cov-$RUN.tgz $USER_HOME/html-report/$RUN' $USER"
                rlFileSubmit "$USER_HOME/cov-$RUN.tgz"
            fi

            # Upload file so one can review ASAP
            rlRun "tar czf /tmp/$RUN.tgz $USER_HOME/$RUN"
            rlFileSubmit /tmp/$RUN.tgz && rm -f /tmp/$RUN.tgz
        rlPhaseEnd
    done

    rlPhaseStartCleanup
        if [[ $COVERAGE -eq 1 ]]; then
            # Combine all coverage data
            rlRun "su -l -c 'coverage combine --rcfile=$USER_COVERAGERC $USER_COVER_DIR/*' $USER"
            rlRun "su -l -c 'coverage report --rcfile=$USER_COVERAGERC' $USER"
            rlRun "su -l -c 'coverage html -d $USER_HOME/html-report/combined --rcfile=$USER_COVERAGERC' $USER"

            rlFileSubmit $USER_COVER_FINAL
            rlRun "su -l -c 'tar czf $USER_HOME/coverage-html.tgz $USER_HOME/html-report/combined' $USER"
            rlFileSubmit $USER_HOME/coverage-html.tgz
        fi

        rlRun "su -l -c 'tmt run --id $CONNECT_RUN plans --default finish' $USER"
        rlFileRestore
        rlRun "pkill -u $USER" 0,1
        rlRun "loginctl terminate-user $USER" 0,1
        rlRun "userdel -r $USER"
    rlPhaseEnd
rlJournalEnd
