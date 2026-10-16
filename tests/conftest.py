import pytest

from brainhops_eval.fixtures import generate


@pytest.fixture(scope="session")
def inputs(tmp_path_factory):
    return generate(tmp_path_factory.mktemp("images"))


@pytest.fixture(scope="session")
def fixtures(inputs, tmp_path_factory):
    from software.simpleitk.generate import generate
    return generate(inputs, tmp_path_factory.mktemp("native"), extended=False)

