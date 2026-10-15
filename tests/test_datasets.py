import hashlib
import io

import pytest

from brainhops_eval.datasets import fetch
from brainhops_eval.files import read_json, write_json


def test_download_verifies_bytes_and_repairs_cache(tmp_path, monkeypatch):
    data = b"anatomical image contents"
    checksum = hashlib.sha256(data).hexdigest()
    manifest = tmp_path / "sources.json"
    (tmp_path / "LICENSE.txt").write_text("Example dataset license notice")
    write_json(manifest, {"datasets": {"test": {
        "url": "https://example.org/pinned/image.nii", "filename": "image.nii",
        "sha256": checksum, "license": "CC0", "version": "snapshot-1", "license_file": "LICENSE.txt",
    }}})
    calls = []

    def download(*args, **kwargs):
        calls.append(args)
        return io.BytesIO(data)

    monkeypatch.setattr("urllib.request.urlopen", download)
    target = fetch(manifest, "test", tmp_path / "cache")
    assert target.read_bytes() == data
    assert target.with_name(target.name + ".LICENSE.txt").read_text() == "Example dataset license notice"
    assert read_json(target.with_name(target.name + ".source.json"))["sha256"] == checksum
    fetch(manifest, "test", tmp_path / "cache")
    assert len(calls) == 1
    target.write_bytes(b"corrupted cache")
    fetch(manifest, "test", tmp_path / "cache")
    assert len(calls) == 2 and target.read_bytes() == data


def test_failed_download_leaves_no_cache_entry(tmp_path, monkeypatch):
    manifest = tmp_path / "sources.json"
    write_json(manifest, {"datasets": {"test": {
        "url": "https://example.org/image.nii", "filename": "image.nii",
        "sha256": "0" * 64, "license": "CC0", "version": "snapshot-1",
    }}})
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: io.BytesIO(b"wrong"))
    with pytest.raises(ValueError, match="checksum mismatch"):
        fetch(manifest, "test", tmp_path / "cache")
    assert not list((tmp_path / "cache").iterdir())

