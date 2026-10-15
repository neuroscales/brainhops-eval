"""Download explicitly selected files, verifying bytes before caching."""

import re
import tempfile
import urllib.request
from pathlib import Path

from .files import digest, read_json, relative_file, write_json


def fetch(manifest_path, name, cache):
    entry = read_json(manifest_path)["datasets"][name]
    checksum = entry["sha256"]
    if not re.fullmatch(r"[0-9a-f]{64}", checksum):
        raise ValueError("Dataset requires a full SHA256 checksum")
    if not entry.get("license") or not entry.get("version"):
        raise ValueError("Dataset requires license and version provenance")
    if not entry["url"].startswith("https://"):
        raise ValueError("Dataset URL must use HTTPS")
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    target = relative_file(cache, entry["filename"])
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or digest(target) != checksum:
        # Stream to a temporary file on the same filesystem; a failed request
        # or checksum must never leave an apparently complete cache entry.
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
            temporary = Path(stream.name)
            try:
                with urllib.request.urlopen(entry["url"], timeout=120) as response:
                    while block := response.read(1024 * 1024):
                        stream.write(block)
                stream.close()
                if digest(temporary) != checksum:
                    raise ValueError(f"Dataset checksum mismatch: {name}")
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
    write_json(target.with_name(target.name + ".source.json"), entry)
    return target

