"""Shared annotations for JSON fixture records and filesystem paths.

Brainhops remains an optional runtime dependency: native fixture generators can
import this package without importing the version under evaluation.
"""

from pathlib import Path
from typing import Any, TypeAlias

import numpy.typing as npt

PathLike: TypeAlias = str | Path
Record: TypeAlias = dict[str, Any]
Array: TypeAlias = npt.NDArray[Any]
