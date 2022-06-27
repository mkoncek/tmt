import os

import tmt

ROOT = "/home/lzachar/gits/tmt/WIP"


def set_options(sources):
    if sources != ['.']:
        sources = [os.path.join(ROOT, i) for i in sources]

    tmt.Test._options = {
        'sources': True,
        'names': sources,
        }


tree = tmt.Tree('.')


def m():
    r = [t.name for t in tree.tests()]
    print(r)
    return r


set_options(["."])
assert ['/d', '/a/c', '/aa', '/b/bb'] == m()

set_options(["main.fmf"])
assert ['/d', '/a/c', '/aa', '/b/bb'] == m()

set_options(["a/main.fmf"])
assert ['/a/c'] == m()

set_options(["aa/main.fmf", "b/bb.fmf"])
assert ['/aa', '/b/bb'] == m()
