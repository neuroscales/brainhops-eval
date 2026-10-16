"""Portable manifests and content integrity."""

import hashlib
import json
from pathlib import Path
from typing import Any

from .types import PathLike, Record


def digest(path: PathLike) -> str:
    """Stream the SHA256 digest of a file without loading it into memory."""
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: PathLike, value: Any) -> None:
    """Write readable strict JSON, refusing NaN and infinity."""
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def read_json(path: PathLike) -> Any:
    """Decode a UTF-8 JSON file without interpreting array or image formats."""
    return json.loads(Path(path).read_text())


def relative_file(root: PathLike, name: PathLike) -> Path:
    """Resolve a bundle path and reject traversal or symlinks outside its root."""
    root = Path(root).resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"Path escapes fixture directory: {name}")
    return path


def inventory(root: PathLike) -> dict[str, str]:
    """Hash all files below a bundle root except the manifest itself."""
    return {
        str(path.relative_to(root)): digest(path)
        for path in sorted(Path(root).rglob("*"))
        if path.is_file() and path.name != "manifest.json"
    }


def verify(root: PathLike, manifest: Record) -> None:
    """Verify a schema-1 manifest and raise on any missing or modified file."""
    if manifest["schema_version"] != 1:
        raise ValueError("Unsupported fixture schema")
    for name, expected in manifest["files"].items():
        if digest(relative_file(root, name)) != expected:
            raise ValueError(f"Checksum mismatch: {name}")
