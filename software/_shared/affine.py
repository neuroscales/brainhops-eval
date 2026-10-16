"""Bundle bookkeeping for command-line affine recipes; no brainhops imports."""

import argparse
from pathlib import Path
import shutil
import subprocess

import nibabel as nib
import numpy as np
from scipy.ndimage import affine_transform

from brainhops_eval.files import digest, inventory, read_json, verify, write_json


def command(arguments, log, *, cwd=None):
    arguments = [str(value) for value in arguments]
    process = subprocess.run(arguments, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=cwd)
    with Path(log).open("a") as stream:
        stream.write(repr(arguments) + "\n" + process.stdout + "\n")
    process.check_returncode()
    return process.stdout.strip()


def interior(source, reference, pull, degree):
    """Independent geometric overlap, excluding native boundary conventions."""
    src, ref = nib.load(source), nib.load(reference)
    matrix = np.linalg.inv(src.affine) @ pull @ ref.affine
    indices = np.indices(ref.shape, dtype=float).reshape(3, -1)
    points = matrix[:3, :3] @ indices + matrix[:3, 3, None]
    margin = 1 if degree else 0.5
    return np.all((points >= margin) &
                  (points <= np.array(src.shape)[:, None] - 1 - margin), axis=0).reshape(ref.shape)


def fsl_scaled(image):
    """Voxel indices to FSL scaled mm, including its determinant-dependent flip."""
    matrix = np.diag([*image.header.get_zooms()[:3], 1.]).astype(float)
    if np.linalg.det(image.affine[:3, :3]) > 0:
        matrix[0, 0] *= -1
        matrix[0, 3] = (image.shape[0] - 1) * image.header.get_zooms()[0]
    return matrix


def flirt_from_pull(pull, moving, reference):
    mov, ref = nib.load(moving), nib.load(reference)
    return fsl_scaled(ref) @ np.linalg.inv(ref.affine) @ np.linalg.inv(pull) @ mov.affine @ np.linalg.inv(fsl_scaled(mov))


def pull_from_flirt(matrix, moving, reference):
    mov, ref = nib.load(moving), nib.load(reference)
    return mov.affine @ np.linalg.inv(fsl_scaled(mov)) @ np.linalg.inv(matrix) @ fsl_scaled(ref) @ np.linalg.inv(ref.affine)


def build(inputs, output, *, backend, register, write_transform, apply_image,
          hint, convention, image_options=False, container_image=None):
    inputs, output = Path(inputs).resolve(), Path(output).resolve()
    verify(inputs, read_json(inputs / "manifest.json"))
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use an empty output directory to avoid stale fixtures")
    output.mkdir(parents=True, exist_ok=True)
    shutil.copytree(inputs, output / "inputs")
    inputs = output / "inputs"
    transforms = output / "transforms"
    transforms.mkdir()
    log = output / "commands.log"
    fixed, moving = inputs / "fixed.nii.gz", inputs / "moving.nii.gz"
    estimated, native_path, registration = register(moving, fixed, transforms, log)
    landmarks = read_json(inputs / "landmarks.json")
    known = np.linalg.inv(landmarks["push_moving_to_fixed_ras"])
    points = np.array(landmarks["fixed"])
    observed = points @ estimated[:3, :3].T + estimated[:3, 3]
    registration["landmark_error_mm"] = np.linalg.norm(observed - landmarks["moving"], axis=1).tolist()
    write_json(output / "registration.json", {
        "backend": backend, "registration": registration, "threads": 1,
        "container_sha256": digest(container_image) if container_image else None})
    cases = []
    for mode, pull in [("known", known), ("registered", estimated)]:
        # Preserve the original native registration output, including its precision.
        original = native_path if mode == "registered" else write_transform(
            transforms / "known.txt", pull, moving, fixed)
        for variant in read_json(inputs / "inputs.json")["variants"]:
            case = dict(variant, id=f"{mode}-{variant['id']}", kind="nifti",
                        moving="inputs/" + variant["moving"], reference="inputs/" + variant["reference"],
                        transform=str(original.relative_to(output)), transform_hint=hint)
            src, ref = output / case["moving"], output / case["reference"]
            if image_options:
                # Geometry belongs to the matrix's original registration pair,
                # even when applying it to a different sampling of that world.
                case["transform_images"] = {"moving": "inputs/moving.nii.gz", "reference": "inputs/fixed.nii.gz"}
            folder = output / "cases" / case["id"]
            folder.mkdir(parents=True)
            # FSL and transformix need the same world map encoded for this grid.
            rebased = write_transform(folder / "native-grid.txt", pull, src, ref)
            apply_image(src, ref, rebased, case["degree"], folder / "expected.nii.gz", log)
            mask = interior(src, ref, pull, case["degree"])
            np.save(folder / "interior.npy", mask)
            # Validate native conventions independently before accepting a fixture.
            source, reference = nib.load(src), nib.load(ref)
            expected_image = nib.load(folder / "expected.nii.gz")
            orientation = nib.orientations.ornt_transform(
                nib.orientations.io_orientation(expected_image.affine),
                nib.orientations.io_orientation(reference.affine))
            aligned = expected_image.as_reoriented(orientation)
            if aligned.shape != reference.shape or not np.allclose(aligned.affine, reference.affine, atol=1e-4, rtol=1e-6):
                raise ValueError("Native resampler changed the requested world grid")
            voxel_pull = np.linalg.inv(source.affine) @ pull @ reference.affine
            oracle = affine_transform(source.get_fdata(), voxel_pull[:3, :3], voxel_pull[:3, 3],
                                      output_shape=reference.shape, order=case["degree"], mode="constant")
            error = float(np.max(np.abs(oracle[mask] - aligned.get_fdata()[mask])))
            # Native integer outputs may truncate or round. Record that difference;
            # this loose fixture validation is separate from strict brainhops checks.
            tolerance = 1.01 if aligned.get_data_dtype().kind in "iu" else 0.02
            if error > tolerance:
                raise ValueError(f"Native {case['id']} disagrees with independent RAS pull: {error}")
            case["native_world_oracle_max_abs"] = error
            case.update(expected=f"cases/{case['id']}/expected.nii.gz", mask=f"cases/{case['id']}/interior.npy")
            cases.append(case)
    write_json(output / "geometry-probes.json", {})
    write_json(output / "cases.json", {"schema_version": 1, "backend": backend,
               "transform_convention": convention,
               "boundary": "native boundary convention recorded in boundary-probes.json; interpolation edges excluded from interior criteria", "cases": cases})
    write_json(output / "manifest.json", {"schema_version": 1, "files": inventory(output)})
    from software._shared.boundaries import probe
    probe(output, backend, write_transform, apply_image,
          extension='mat' if backend == 'fsl' else 'txt')
    return output


def main(generate):
    parser = argparse.ArgumentParser(description=generate.__doc__)
    parser.add_argument("--inputs", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--container-image")
    generate(**vars(parser.parse_args()))
