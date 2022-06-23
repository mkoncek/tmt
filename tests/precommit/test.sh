#!/bin/bash
# vim: dict+=/usr/share/beakerlib/dictionary.vim cpt=.,w,b,u,t,i,k
. /usr/share/beakerlib/beakerlib.sh || exit 1

rlJournalStart
    rlPhaseStartSetup
        export REPO="$(pwd)/../.."
        export REV="$(git rev-parse --short HEAD)"
        rlRun "tmp=\$(mktemp -d)" 0 "Creating tmp directory"
        rlRun "pushd $tmp"
        rlRun "set -o pipefail"
        rlRun "tmt init"
    rlPhaseEnd

    rlPhaseStartTest
        rlRun "git init"
        rlRun "git config --local user.name LZachar"
        rlRun "git config --local user.email lzachar@redhat.com"
cat <<EOF > .pre-commit-config.yaml
repos:
  - repo: $REPO
    rev: $REV
    hooks:
    - id: tmt-test-lint
EOF
        rlRun "cat .pre-commit-config.yaml"
        rlRun -s "pre-commit install"
        rlAssertGrep 'pre-commit installed' $rlRun_LOG
        rlRun -s "git add .pre-commit-config.yaml"
        rlRun -s "git commit -m nothing_to_check"
        rlAssertGrep 'tmt tests lint.*no files to check' $rlRun_LOG
        rlRun "echo 'test: echo' > main.fmf"
        rlRun "git add main.fmf"
        rlRun -s "git commit -m 'missing_fmf'" "1"
        rlAssertGrep 'tmt tests lint.*Failed' $rlRun_LOG

        rlRun "git add .fmf/version"
        rlRun -s "git commit -m 'pass'"
        rlAssertGrep 'tmt tests lint.*Passed' $rlRun_LOG

        rlRun "echo foo: bar >> main.fmf"
        rlRun -s "git commit -a -m wrong" "1"
        rlAssertGrep 'tmt tests lint.*Failed' $rlRun_LOG
        rlAssertGrep 'fail unknown attribute' $rlRun_LOG
    rlPhaseEnd

    rlPhaseStartCleanup
        rlRun "popd"
        rlRun "rm -rf $tmp" 0 "Removing tmp directory"
    rlPhaseEnd
rlJournalEnd
