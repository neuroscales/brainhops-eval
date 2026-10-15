import pytest

from brainhops_eval.fixtures import generate


@pytest.fixture(scope="session")
def inputs(tmp_path_factory):
    return generate(tmp_path_factory.mktemp("images"))


@pytest.fixture(scope="session")
def fixtures(inputs, tmp_path_factory):
    from brainhops_eval.adapters.simpleitk import build
    return build(inputs, tmp_path_factory.mktemp("native"))

