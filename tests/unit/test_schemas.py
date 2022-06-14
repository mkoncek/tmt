import os
import subprocess

import pytest
from ruamel.yaml import YAML

import tmt
import tmt.utils

PATH = os.path.dirname(os.path.realpath(__file__))
SCHEMADIR = os.path.join(PATH, "../../tmt/schemas")
ROOTDIR = os.path.join(PATH, "../..")

# make sure tmt tree is initialized, required when tests run during rpmbuild
tmt.base.Tree.init(ROOTDIR, 'empty', False)


@pytest.fixture
def schema_and_store():
    return tmt.utils.load_schema('tests.yaml'), tmt.utils.load_schema_store()


@pytest.fixture(params=tmt.Tree('.').tests())
def test_result(request, schema_and_store):
    schema, store = schema_and_store
    return request.param.node.validate(schema, store)


def test_test_schema(test_result):
    if not test_result.result:
        for error in test_result.errors:
            print(error)

    assert test_result.result
