"""Select native recipes from folders, without importing software runtimes."""

import json
import re
import sys
from pathlib import Path


def select(selection, root):
    available = sorted(path.parent.name for path in Path(root).glob("*/container.def")
                       if re.fullmatch(r"[a-z0-9][a-z0-9_-]*", path.parent.name))
    if not available:
        raise ValueError("No software recipes found")
    if selection == "all":
        return available
    names = list(dict.fromkeys(name.strip() for name in selection.split(",")))
    if any(name not in available for name in names):
        raise ValueError(f"Unknown software selection {selection!r}; available: {', '.join(available)}")
    return names


if __name__ == "__main__":
    print(json.dumps(select(sys.argv[1], Path(__file__).resolve().parents[1] / "software")))
