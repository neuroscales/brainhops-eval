"""Portable manifests and content integrity."""

import hashlib
import json
from pathlib import Path


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def read_json(path):
    return json.loads(Path(path).read_text())


def relative_file(root, name):
    root = Path(root).resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"Path escapes fixture directory: {name}")
    return path


def inventory(root):
    return {
        str(path.relative_to(root)): digest(path)
        for path in sorted(Path(root).rglob("*"))
        if path.is_file() and path.name != "manifest.json"
    }


def verify(root, manifest):
    if manifest["schema_version"] != 1:
        raise ValueError("Unsupported fixture schema")
    for name, expected in manifest["files"].items():
        if digest(relative_file(root, name)) != expected:
            raise ValueError(f"Checksum mismatch: {name}")

