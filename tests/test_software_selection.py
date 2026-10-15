import pytest

from scripts.select_software import select


def test_discovery_needs_only_a_software_folder(tmp_path):
    for name in ("ants", "new-tool", "simpleitk"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "container.def").write_text("test definition")
    (tmp_path / "_shared").mkdir()
    assert select("all", tmp_path) == ["ants", "new-tool", "simpleitk"]
    assert select("simpleitk, new-tool, simpleitk", tmp_path) == ["simpleitk", "new-tool"]
    with pytest.raises(ValueError, match="Unknown software"):
        select("../other", tmp_path)
