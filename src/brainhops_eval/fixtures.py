"""Deterministic synthetic anatomy and world-preserving grid changes."""

from pathlib import Path

import nibabel as nib
import numpy as np
from PIL import Image
from scipy.ndimage import affine_transform, map_coordinates

from .files import digest, inventory, read_json, write_json


def grid(shape, spacing, angle=0):
    c, s = np.cos(angle), np.sin(angle)
    matrix = np.eye(4)
    matrix[:3, :3] = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]]) @ np.diag(spacing)
    matrix[:3, 3] = -matrix[:3, :3] @ ((np.array(shape) - 1) / 2)
    return matrix


def coordinates(shape, affine):
    index = np.indices(shape, dtype=float).reshape(3, -1)
    return (affine[:3, :3] @ index + affine[:3, 3, None]).reshape((3, *shape))


def phantom(points):
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


def save_nifti(path, data, affine):
    image = nib.Nifti1Image(data, affine)
    image.header.set_xyzt_units("mm")
    image.set_sform(affine, code=1)
    image.set_qform(affine, code=1)
    nib.save(image, path)


def regrid(data, old_affine, shape, new_affine, degree=1):
    pull = np.linalg.inv(old_affine) @ new_affine
    return affine_transform(
        data.astype(np.float32), pull[:3, :3], pull[:3, 3],
        output_shape=shape, order=degree, mode="constant", cval=0,
    )


def write_itk_affine(path, matrix):
    """Write an explicit physical pull mapping, with centre zero."""
    ndim = matrix.shape[0] - 1
    parameters = list(matrix[:ndim, :ndim].ravel()) + list(matrix[:ndim, ndim])
    Path(path).write_text(
        "#Insight Transform File V1.0\n#Transform 0\n"
        f"Transform: AffineTransform_double_{ndim}_{ndim}\n"
        + "Parameters: " + " ".join(map(str, parameters)) + "\n"
        + "FixedParameters: " + " ".join(["0"] * ndim) + "\n"
    )


def generate(output, source=None):
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use an empty output directory to avoid stale fixtures")
    output.mkdir(parents=True, exist_ok=True)
    shape = (48, 52, 40)
    spacing = np.array([1.2, 1.1, 1.5])
    provenance = {"kind": "analytic-phantom", "version": 1}
    sample = phantom
    if source:
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

        def sample(points):
            flat = points.reshape(3, -1)
            indices = inverse[:3, :3] @ flat + inverse[:3, 3, None]
            return map_coordinates(values, indices, order=1, mode="constant").reshape(points.shape[1:])

        provenance = {"kind": "anatomical", "sha256": digest(source), "filename": source.name,
                      "intensity_percentiles": [float(lo), float(hi)],
                      "original_affine": image.affine.tolist()}
        sidecar = source.with_name(source.name + ".source.json")
        if sidecar.exists():
            provenance["dataset"] = read_json(sidecar)

    fixed_affine = grid(shape, spacing)
    fixed = sample(coordinates(shape, fixed_affine)).astype(np.float32)
    # The anatomical mapping moves moving RAS coordinates into fixed RAS.
    push = grid((1, 1, 1), (1, 1, 1), np.deg2rad(5))
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
    save_nifti(output / "fixed.nii.gz", fixed, fixed_affine)
    save_nifti(output / "moving.nii.gz", moving, moving_affine)
    reflection = np.eye(4)
    reflection[0, 0] = -1
    reflection[0, 3] = moving.shape[0] - 1
    save_nifti(output / "moving-left-handed.nii.gz", moving[::-1], moving_affine @ reflection)

    new_shape = tuple(np.ceil((np.array(moving.shape) - 1) / 1.7).astype(int) + 1)
    new_affine = moving_affine @ np.diag([1.7, 1.7, 1.7, 1])
    save_nifti(output / "moving-downsampled.nii.gz",
               regrid(moving, moving_affine, new_shape, new_affine), new_affine)
    save_nifti(output / "moving-uint8.nii.gz", np.clip(moving / 5, 0, 255).astype(np.uint8), moving_affine)
    reference_shape = (39, 43, 33)
    reference_affine = grid(reference_shape, spacing * 1.25, np.deg2rad(13))
    save_nifti(output / "reference-oblique.nii.gz",
               regrid(fixed, fixed_affine, reference_shape, reference_affine), reference_affine)
    # Label maps share source geometry and use nearest interpolation.
    labels = ((moving > 250).astype(np.uint8) + (moving > 650).astype(np.uint8))
    save_nifti(output / "moving-labels.nii.gz", labels, moving_affine)
    flip = np.diag([-1., -1., 1., 1.])
    write_itk_affine(output / "known-pull.tfm", flip @ np.linalg.inv(push) @ flip)
    landmarks = np.array([[-9, 2, 0], [10, -3, 3], [-14, -12, 10], [7, 14, -9]], dtype=float) * (spacing / [1.2, 1.1, 1.5])
    pull = np.linalg.inv(push)
    write_json(output / "landmarks.json", {
        "coordinate_system": "RAS", "unit": "mm",
        "fixed": landmarks.tolist(),
        "moving": (landmarks @ pull[:3, :3].T + pull[:3, 3]).tolist(),
        "push_moving_to_fixed_ras": push.tolist(),
    })
    variants = [
        {"id": "native", "moving": "moving.nii.gz", "reference": "fixed.nii.gz", "degree": 1},
        {"id": "left-handed", "moving": "moving-left-handed.nii.gz", "reference": "fixed.nii.gz", "degree": 1},
        {"id": "moving-downsampled", "moving": "moving-downsampled.nii.gz", "reference": "fixed.nii.gz", "degree": 1},
        {"id": "reference-oblique", "moving": "moving.nii.gz", "reference": "reference-oblique.nii.gz", "degree": 1},
        {"id": "uint8", "moving": "moving-uint8.nii.gz", "reference": "fixed.nii.gz", "degree": 1},
        {"id": "labels", "moving": "moving-labels.nii.gz", "reference": "fixed.nii.gz", "degree": 0},
    ]
    # Native PNG and NPY use the same non-square row/column array. No DPI.
    yy, xx = np.indices((47, 63), dtype=float)

    def raster(x, y):
        return np.clip(180 * np.exp(-((x - 20) / 9) ** 2 - ((y - 25) / 12) ** 2)
                       + 110 * ((x > 42) & (x < 49) & (y > 8) & (y < 18)), 0, 255).astype(np.uint8)

    for name, data in [("fixed", raster(xx, yy)), ("moving", raster(xx + 3, yy - 2))]:
        Image.fromarray(data).save(output / f"{name}.png")
        np.save(output / f"{name}.npy", data, allow_pickle=False)
    raster_pull = np.eye(3)
    raster_pull[:2, 2] = [-3, 2]
    write_itk_affine(output / "raster-known-pull.tfm", raster_pull)
    write_json(output / "inputs.json", {
        "schema_version": 1, "source": provenance, "variants": variants,
        "raster_policy": {"storage_axes": ["y", "x"], "model_axes": ["x", "y"],
                          "pixel_centres": "integers", "origin": [0, 0],
                          "spacing": [1, 1], "direction": [[1, 0], [0, 1]],
                          "note": "SimpleITK defaults; explicitly adopted for npy GetImageFromArray"},
    })
    manifest = {"schema_version": 1, "files": inventory(output)}
    write_json(output / "manifest.json", manifest)
    return output

