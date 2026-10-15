"""Extract a small FLIRT runtime from a verified upstream Docker layer.

Streaming avoids unpacking the multi-gigabyte atlas/data installation in CI.
The pinned layer belongs to brainlife/fsl:6.0.4, manifest
sha256:3aed9764f37c9ca36874c663ede6049d0d7f37bc1eaaf53a0b6bc9fdd7d7e62a.
"""

import hashlib
import json
from pathlib import Path
import sys
import tarfile
import urllib.request

LAYER = "sha256:8b22cc78a1b280b6a88cda4959b019bf9681593b2cf80987127c146ea0251dee"
PREFIX = "usr/local/fsl/"


class VerifiedStream:
    def __init__(self, stream):
        self.stream, self.hash = stream, hashlib.sha256()

    def read(self, size=-1):
        data = self.stream.read(size)
        self.hash.update(data)
        return data


def extract(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    url = "https://auth.docker.io/token?service=registry.docker.io&scope=repository:brainlife/fsl:pull"
    with urllib.request.urlopen(url) as response:
        token = json.load(response)["token"]
    request = urllib.request.Request("https://registry-1.docker.io/v2/brainlife/fsl/blobs/" + LAYER,
                                     headers={"Authorization": "Bearer " + token})
    found = []
    with urllib.request.urlopen(request) as response:
        verified = VerifiedStream(response)
        with tarfile.open(fileobj=verified, mode="r|gz") as archive:
            for member in archive:
                name = member.name.removeprefix("./")
                if not name.startswith(PREFIX):
                    continue
                relative = name[len(PREFIX):]
                if not (relative in ("bin/flirt", "etc/fslversion") or
                        relative.startswith("lib/") or "licen" in relative.lower()):
                    continue
                target = destination / relative
                if ".." in Path(relative).parts or Path(relative).is_absolute():
                    raise ValueError("Unsafe archive path")
                if member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.extractfile(member) as source, target.open("wb") as output:
                        while chunk := source.read(1024 * 1024):
                            output.write(chunk)
                    target.chmod(member.mode & 0o777)
                    found.append(relative)
                elif member.issym():
                    # Retain only relative links confined to the runtime directory.
                    link = (target.parent / member.linkname).resolve()
                    if not link.is_relative_to(destination.resolve()):
                        raise ValueError("Unsafe runtime symlink")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.symlink_to(member.linkname)
        while verified.read(1024 * 1024):
            pass
        if "sha256:" + verified.hash.hexdigest() != LAYER:
            raise ValueError("FSL upstream layer checksum mismatch")
    if not (destination / "bin/flirt").is_file():
        raise ValueError("Upstream layer contains no FLIRT executable")
    (destination / "runtime-source.json").write_text(json.dumps({"image": "brainlife/fsl:6.0.4", "layer": LAYER, "files": found}, indent=2))


if __name__ == "__main__":
    extract(sys.argv[1])
