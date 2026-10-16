"""Execute the public brainhops API or CLI on original reader objects.

Only native reference arrays may be reordered losslessly. Loaded brainhops
images are never rebuilt, cast, relabelled, or given replacement geometry.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import nibabel as nib
import numpy as np

from .axes import raster_axis_check
from .boundaries import reslice_options
from .files import relative_file
from .types import Array, PathLike, Record


@dataclass(frozen=True)
class CasePaths:
    """Resolved files used by one application, with bundle containment checks."""

    source: Path
    reference: Path
    transform: Path
    expected: Path
    mask: Path
    output: Path

    @classmethod
    def resolve(cls, fixtures: PathLike, output: PathLike, case: Record) -> CasePaths:
        """Resolve the five fixture paths and the case's output directory."""
        return cls(
            *(
                relative_file(fixtures, case[key])
                for key in ("moving", "reference", "transform", "expected", "mask")
            ),
            output=Path(output),
        )


@dataclass(frozen=True)
class ReslicedArrays:
    """Decoded output and reference-panel values, without altering image objects."""

    actual: Array
    reference: Array


def load_array(path: PathLike) -> Array:
    """Read a reference NPY array or decoded NIfTI values; NPY is not an image input."""
    return (
        np.load(path, allow_pickle=False)
        if Path(path).suffix == ".npy"
        else nib.load(path).get_fdata()
    )


def expected_on_reference_grid(path: PathLike, reference: PathLike) -> tuple[Array, list]:
    """Undo native storage-axis permutations/flips without interpolating values.

    Raise when lossless reordering cannot place the native output exactly on
    the requested reference grid. This does not edit either input to brainhops.
    """
    image, ref = nib.load(path), nib.load(reference)
    orientation = nib.orientations.ornt_transform(
        nib.orientations.io_orientation(image.affine), nib.orientations.io_orientation(ref.affine)
    )
    aligned = image.as_reoriented(orientation)
    if aligned.shape != ref.shape or not np.allclose(
        aligned.affine, ref.affine, atol=1e-4, rtol=1e-6
    ):
        raise ValueError(
            "Native output is not on the reference grid, even after lossless axis reordering"
        )
    return aligned.get_fdata(), orientation.tolist()


def transform_source(fixtures: PathLike, case: Record) -> str:
    """Encode a CLI source specification with hints and original image geometries."""
    spec = quote(str(relative_file(fixtures, case["transform"])), safe="/:._-")
    if case.get("transform_hint"):
        spec += "|" + case["transform_hint"]
    for name, value in case.get("transform_options", {}).items():
        encoded = str(value).lower() if isinstance(value, bool) else str(value)
        spec += f"|{name}:{encoded}"
    for name, path in case.get("transform_images", {}).items():
        spec += f"|{name}:[{quote(str(relative_file(fixtures, path)), safe='/:._-')}]"
    return spec


def load_transform(bio: Any, fixtures: PathLike, case: Record) -> Any:
    """Load a transform through the selected brainhops version's public reader.

    ``bio`` is its io module; passing it explicitly keeps brainhops optional for
    native fixture generation and makes the unmodified reader contract testable.
    """
    options = dict(case.get("transform_options", {}))
    options.update(
        {
            name: bio.images.load(relative_file(fixtures, path))
            for name, path in case.get("transform_images", {}).items()
        }
    )
    if case.get("transform_hint"):
        options["hint"] = case["transform_hint"]
    return bio.load(relative_file(fixtures, case["transform"]), **options)


def _apply_python(
    bio: Any, fixtures: PathLike, paths: CasePaths, case: Record, record: Record
) -> tuple[Any, Any, Any]:
    """Load original source/reference images and invoke their documented methods."""
    record["stage"] = "load images and transform"
    source = bio.images.load(paths.source)
    reference = bio.images.load(paths.reference)
    pull = load_transform(bio, fixtures, case)
    record["stage"] = "apply transform and reslice"
    resliced = source(pull).reslice(
        reference, degree=case["degree"], **reslice_options(record["boundary_policy"])
    )
    return resliced, source, reference


def _validate_nifti(paths: CasePaths, case: Record, record: Record) -> ReslicedArrays:
    """Decode saved output, check reference geometry, and preserve its actual dtype."""
    record["stage"] = "validate output grid and values"
    image = nib.load(paths.output / "brainhops.nii.gz")
    reference, source = nib.load(paths.reference), nib.load(paths.source)
    record["input"] = dict(
        shape=list(source.shape),
        dtype=str(source.get_data_dtype()),
        affine_ras=source.affine.tolist(),
        axcodes=list(nib.aff2axcodes(source.affine)),
    )
    record["reference"] = dict(shape=list(reference.shape), affine_ras=reference.affine.tolist())
    if image.shape != reference.shape or not np.allclose(
        image.affine, reference.affine, atol=1e-4, rtol=1e-6
    ):
        raise ValueError("brainhops output geometry differs from the reference grid")
    actual = np.asanyarray(image.dataobj)
    record["output_dtype"] = str(image.get_data_dtype())
    if case["degree"] == 0:
        allowed = np.append(np.unique(source.get_fdata()), 0)
        if not np.isin(actual, allowed).all():
            raise ValueError("Nearest interpolation introduced a new label value")
    return ReslicedArrays(actual, reference.get_fdata())


def python_nifti(
    bio: Any, fixtures: PathLike, paths: CasePaths, case: Record, probes: Record, record: Record
) -> ReslicedArrays:
    """Reslice directly loaded NIfTI images and save through brainhops io.save."""
    resliced, _, _ = _apply_python(bio, fixtures, paths, case, record)
    record["in_memory_output_dtype"] = str(resliced.data.dtype)
    record["stage"] = "save output"
    bio.save(resliced, paths.output / "brainhops.nii.gz")
    return _validate_nifti(paths, case, record)


def cli_nifti(
    bio: Any, fixtures: PathLike, paths: CasePaths, case: Record, probes: Record, record: Record
) -> ReslicedArrays:
    """Invoke the installed CLI with its documented push-transform convention."""
    record["stage"] = "run brainhops CLI"
    args = [
        sys.executable,
        "-m",
        "brainhops",
        "reslice",
        str(paths.source),
        "--reference",
        str(paths.reference),
        "--transform",
        transform_source(fixtures, case) + "|inv",
        "--output",
        str(paths.output / "brainhops.nii.gz"),
        "--degree",
        str(case["degree"]),
        "--bound",
        str(record["boundary_policy"]["brainhops_bound"]),
    ]
    if record["boundary_policy"].get("brainhops_clip") is not None:
        args += ["--clip", repr(record["boundary_policy"]["brainhops_clip"])]
    process = subprocess.run(
        args, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    (paths.output / "brainhops.log").write_text(repr(args) + "\n" + process.stdout)
    process.check_returncode()
    return _validate_nifti(paths, case, record)


def python_raster(
    bio: Any, fixtures: PathLike, paths: CasePaths, case: Record, probes: Record, record: Record
) -> ReslicedArrays:
    """Apply to original raster images and inspect their axes without adapting them."""
    resliced, source, reference = _apply_python(bio, fixtures, paths, case, record)
    record["axis_interpretation"] = {
        "moving": raster_axis_check(source, paths.source, probes[case["kind"]]["moving"]),
        "reference": raster_axis_check(
            reference, paths.reference, probes[case["kind"]]["reference"]
        ),
    }
    actual = np.asarray(resliced.data)
    np.save(paths.output / "brainhops.npy", actual)
    record["geometry_policy"] = "unmodified io.images.load defaults"
    return ReslicedArrays(actual, np.asarray(reference.data))


def execute(
    bio: Any, fixtures: PathLike, paths: CasePaths, case: Record, probes: Record, record: Record
) -> ReslicedArrays:
    """Dispatch by image kind and interface; rasters always exercise Python readers."""
    handlers = {"python": python_nifti, "cli": cli_nifti}
    handler = handlers[record["interface"]] if case["kind"] == "nifti" else python_raster
    return handler(bio, fixtures, paths, case, probes, record)
