"""Deterministic synthetic anatomy and world-preserving grid changes."""

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import nibabel as nib
import numpy as np
from PIL import Image
from scipy.ndimage import affine_transform, map_coordinates

from .files import digest, inventory, read_json, write_json
from .types import Array, PathLike, Record

_SHAPE = (48, 52, 40)


def grid(shape: tuple[int, ...], spacing: Array | tuple, angle: float = 0) -> Array:
    """Return a centred RAS voxel grid with a rotation about the superior axis."""
    c, s = np.cos(angle), np.sin(angle)
    matrix = np.eye(4)
    matrix[:3, :3] = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]]) @ np.diag(spacing)
    matrix[:3, 3] = -matrix[:3, :3] @ ((np.array(shape) - 1) / 2)
    return matrix


def coordinates(shape: tuple[int, ...], affine: Array) -> Array:
    """Map voxel centres to physical RAS coordinates, with components first."""
    index = np.indices(shape, dtype=float).reshape(3, -1)
    return (affine[:3, :3] @ index + affine[:3, 3, None]).reshape((3, *shape))


def phantom(points: Array) -> Array:
    """Sample asymmetric high-dynamic-range anatomy in physical RAS millimetres."""
    result = np.zeros(points.shape[1:], dtype=float)
    for center, width, amplitude in [
        ((-9, 2, 0), (8, 13, 11), 700),
        ((10, -3, 3), (10, 9, 13), 900),
        ((-14, -12, 10), (3, 4, 5), 500),
        ((7, 14, -9), (5, 3, 4), 650),
    ]:
        radius = sum(((points[d] - center[d]) / width[d]) ** 2 for d in range(3))
        result += amplitude * np.exp(-radius / 2)
    # Off-centre bars make flips, permutation, and thin-structure loss visible.
    result += 250 * ((abs(points[0] + 17) < 1.5) & (abs(points[1]) < 9) & (abs(points[2]) < 8))
    return result


def save_nifti(path: PathLike, data: Array, affine: Array) -> None:
    """Write explicit millimetre geometry with matching sform/qform and no scaling."""
    image = nib.Nifti1Image(data, affine)
    image.header.set_xyzt_units("mm")
    image.set_sform(affine, code=1)
    image.set_qform(affine, code=1)
    nib.save(image, path)


def regrid(
    data: Array, old_affine: Array, shape: tuple[int, ...], new_affine: Array, degree: int = 1
) -> Array:
    """Resample native fixture arrays onto another grid in the same world space."""
    pull = np.linalg.inv(old_affine) @ new_affine
    return affine_transform(
        data.astype(np.float32),
        pull[:3, :3],
        pull[:3, 3],
        output_shape=shape,
        order=degree,
        mode="constant",
        cval=0,
    )


@dataclass(frozen=True)
class _AnatomyPair:
    """Source arrays and physical grids before any on-disk image conversion."""

    fixed: Array
    moving: Array
    fixed_affine: Array
    moving_affine: Array
    spacing: Array
    push: Array


def _sampler(source: PathLike | None, output: Path) -> tuple[Callable, Array, Record]:
    """Choose analytic anatomy or verified, normalised, recentered source data."""
    shape = _SHAPE
    if source is None:
        return phantom, np.array([1.2, 1.1, 1.5]), {"kind": "analytic-phantom", "version": 2}
    source = Path(source)
    image = nib.load(source)
    if image.ndim != 3:
        raise ValueError("The anatomical source must be a 3-D scalar image")
    values = image.get_fdata(dtype=np.float32)
    if not np.isfinite(values).all():
        raise ValueError("Anatomical source contains non-finite intensities")
    lo, hi = np.percentile(values, [1, 99.5])
    if hi <= lo:
        raise ValueError("Anatomical source has no usable intensity range")
    values = np.clip((values - lo) / (hi - lo), 0, 1) * 1000
    affine = image.affine.copy()
    affine[:3, 3] = -affine[:3, :3] @ ((np.array(image.shape) - 1) / 2)
    inverse = np.linalg.inv(affine)
    extent = np.abs(affine[:3, :3]) @ (np.array(image.shape) - 1)
    spacing = extent / (np.array(shape) - 1)

    def sample(points: Array) -> Array:
        """Sample normalised anatomy in its recentered physical RAS space."""
        flat = points.reshape(3, -1)
        indices = inverse[:3, :3] @ flat + inverse[:3, 3, None]
        return map_coordinates(values, indices, order=1, mode="constant").reshape(points.shape[1:])

    provenance = {
        "kind": "anatomical",
        "sha256": digest(source),
        "filename": source.name,
        "intensity_percentiles": [float(lo), float(hi)],
        "original_affine": image.affine.tolist(),
    }
    sidecar = source.with_name(source.name + ".source.json")
    if sidecar.exists():
        provenance["dataset"] = read_json(sidecar)
    license_path = source.with_name(source.name + ".LICENSE.txt")
    if license_path.exists():
        shutil.copyfile(license_path, output / "source-LICENSE.txt")
    return sample, spacing, provenance


def _make_pair(sample: Callable, spacing: Array) -> _AnatomyPair:
    """Create mismatched RAS/SLP grids related by a known world-space affine."""
    shape = _SHAPE
    fixed_affine = grid(shape, spacing)
    fixed = sample(coordinates(shape, fixed_affine)).astype(np.float32)
    # The anatomical mapping moves moving RAS coordinates into fixed RAS.
    push = grid((1, 1, 1), (1, 1, 1), np.deg2rad(5))
    push[:3, :3] = push[:3, :3] @ np.array([[1.03, 0.04, 0], [0, 0.97, 0.02], [0, 0, 1.02]])
    push[:3, 3] = spacing * np.array([2.5, -1.8, 1.2])
    moving_shape = (45, 49, 37)
    moving_affine = grid(moving_shape, spacing * 1.12, np.deg2rad(-7))
    moving = np.rint(sample(coordinates(moving_shape, push @ moving_affine))).astype(np.int16)
    orient = nib.orientations.ornt_transform(
        nib.orientations.axcodes2ornt(("R", "A", "S")),
        nib.orientations.axcodes2ornt(("S", "L", "P")),
    )
    moving_affine = moving_affine @ nib.orientations.inv_ornt_aff(orient, moving_shape)
    moving = nib.orientations.apply_orientation(moving, orient)
    return _AnatomyPair(fixed, moving, fixed_affine, moving_affine, spacing, push)


def _volume_variants(output: Path, pair: _AnatomyPair) -> None:
    """Write native, reflected, downsampled, oblique and label NIfTI variants."""
    fixed, moving = pair.fixed, pair.moving
    fixed_affine, moving_affine, spacing = pair.fixed_affine, pair.moving_affine, pair.spacing
    save_nifti(output / "fixed.nii.gz", fixed, fixed_affine)
    save_nifti(output / "moving.nii.gz", moving, moving_affine)
    reflection = np.eye(4)
    reflection[0, 0] = -1
    reflection[0, 3] = moving.shape[0] - 1
    save_nifti(output / "moving-left-handed.nii.gz", moving[::-1], moving_affine @ reflection)

    new_shape = tuple(np.ceil((np.array(moving.shape) - 1) / 1.7).astype(int) + 1)
    new_affine = moving_affine @ np.diag([1.7, 1.7, 1.7, 1])
    save_nifti(
        output / "moving-downsampled.nii.gz",
        regrid(moving, moving_affine, new_shape, new_affine),
        new_affine,
    )
    reference_shape = (39, 43, 33)
    reference_affine = grid(reference_shape, spacing * 1.25, np.deg2rad(13))
    save_nifti(
        output / "reference-oblique.nii.gz",
        regrid(fixed, fixed_affine, reference_shape, reference_affine),
        reference_affine,
    )
    # Label maps share source geometry and use nearest interpolation.
    labels = (moving > 250).astype(np.uint8) + (moving > 650).astype(np.uint8)
    save_nifti(output / "moving-labels.nii.gz", labels, moving_affine)
    save_nifti(
        output / "fixed-labels.nii.gz",
        (fixed > 250).astype(np.uint8) + (fixed > 650).astype(np.uint8),
        fixed_affine,
    )


def _integer_variants(output: Path, pair: _AnatomyPair) -> tuple[float, Record]:
    """Quantise both images with shared scaling and require at least 64 bins."""
    fixed, moving = pair.fixed, pair.moving
    fixed_affine, moving_affine = pair.fixed_affine, pair.moving_affine
    intensity_max = float(max(fixed.max(), moving.max()))
    integer_ranges = {}
    for dtype, upper in [(np.uint8, 255), (np.int8, 127)]:
        name = np.dtype(dtype).name
        factor = upper / intensity_max
        for role, values, affine in [
            ("moving", moving, moving_affine),
            ("fixed", fixed, fixed_affine),
        ]:
            quantised = np.rint(np.clip(values * factor, 0, upper)).astype(dtype)
            save_nifti(output / f"{role}-{name}.nii.gz", quantised, affine)
            bins = int(np.unique(quantised).size)
            if bins < 64:
                raise ValueError(f"{role}-{name} occupies only {bins} integer bins")
            integer_ranges[f"{role}-{name}"] = {
                "occupied_bins": bins,
                "minimum": int(quantised.min()),
                "maximum": int(quantised.max()),
                "scale_from_anatomy": factor,
            }

    return intensity_max, integer_ranges


def _landmarks(output: Path, pair: _AnatomyPair) -> None:
    """Write independent physical correspondences and the exact affine truth."""
    spacing, push = pair.spacing, pair.push
    landmarks = np.array([[-9, 2, 0], [10, -3, 3], [-14, -12, 10], [7, 14, -9]], dtype=float) * (
        spacing / [1.2, 1.1, 1.5]
    )
    pull = np.linalg.inv(push)
    write_json(
        output / "landmarks.json",
        {
            "coordinate_system": "RAS",
            "unit": "mm",
            "fixed": landmarks.tolist(),
            "moving": (landmarks @ pull[:3, :3].T + pull[:3, 3]).tolist(),
            "push_moving_to_fixed_ras": push.tolist(),
        },
    )


def _variants(intensity_max: float) -> list[Record]:
    """Declare applications and one shared display window per datatype."""
    variants = [
        {"id": "native", "moving": "moving.nii.gz", "reference": "fixed.nii.gz", "degree": 1},
        {
            "id": "left-handed",
            "moving": "moving-left-handed.nii.gz",
            "reference": "fixed.nii.gz",
            "degree": 1,
        },
        {
            "id": "moving-downsampled",
            "moving": "moving-downsampled.nii.gz",
            "reference": "fixed.nii.gz",
            "degree": 1,
        },
        {
            "id": "reference-oblique",
            "moving": "moving.nii.gz",
            "reference": "reference-oblique.nii.gz",
            "degree": 1,
        },
        {
            "id": "uint8",
            "moving": "moving-uint8.nii.gz",
            "reference": "fixed-uint8.nii.gz",
            "degree": 1,
        },
        {
            "id": "int8",
            "moving": "moving-int8.nii.gz",
            "reference": "fixed-int8.nii.gz",
            "degree": 1,
        },
        {
            "id": "labels",
            "moving": "moving-labels.nii.gz",
            "reference": "fixed-labels.nii.gz",
            "degree": 0,
        },
    ]
    for variant in variants:
        upper = {"uint8": 255, "int8": 127, "labels": 2}.get(variant["id"], intensity_max)
        variant["display_window"] = [0, upper]
    return variants


def _rasters(output: Path) -> None:
    """Write non-square PNGs with known translation and no physical-space metadata."""
    # Native PNG uses a non-square row/column array, without DPI.
    yy, xx = np.indices((47, 63), dtype=float)

    def raster(x: Array, y: Array) -> Array:
        """Return asymmetric byte anatomy in native row/column storage."""
        return np.clip(
            180 * np.exp(-(((x - 20) / 9) ** 2) - ((y - 25) / 12) ** 2)
            + 110 * ((x > 42) & (x < 49) & (y > 8) & (y < 18)),
            0,
            255,
        ).astype(np.uint8)

    for name, data in [("fixed", raster(xx, yy)), ("moving", raster(xx + 3, yy - 2))]:
        Image.fromarray(data).save(output / f"{name}.png")
    raster_pull = np.eye(3)
    raster_pull[:2, 2] = [-3, 2]
    write_json(
        output / "raster-transform.json",
        {
            "pull_reference_to_moving_xy": raster_pull.tolist(),
            "coordinate_system": "fixture model x/y",
            "unit": "pixel",
        },
    )


def generate(output: PathLike, source: PathLike | None = None) -> Path:
    """Build deterministic anatomy, world-preserving grids and integrity metadata.

    ``source`` may be a 3-D anatomical NIfTI downloaded from a declared dataset.
    The default analytic phantom spans hundreds of integer intensity bins.
    """
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use an empty output directory to avoid stale fixtures")
    output.mkdir(parents=True, exist_ok=True)
    sample, spacing, provenance = _sampler(source, output)
    pair = _make_pair(sample, spacing)
    _volume_variants(output, pair)
    intensity_max, integer_ranges = _integer_variants(output, pair)
    _landmarks(output, pair)
    variants = _variants(intensity_max)
    _rasters(output)
    write_json(
        output / "inputs.json",
        {
            "schema_version": 1,
            "source": provenance,
            "variants": variants,
            "integer_intensities": integer_ranges,
            "raster_policy": {
                "storage_axes": ["y", "x"],
                "model_axes": ["x", "y"],
                "pixel_centres": "integers",
                "origin": [0, 0],
                "spacing": [1, 1],
                "direction": [[1, 0], [0, 1]],
                "note": "Intended fixture coordinates; software recipes must probe their reader defaults",
            },
        },
    )
    manifest = {"schema_version": 1, "files": inventory(output)}
    write_json(output / "manifest.json", manifest)
    return output
