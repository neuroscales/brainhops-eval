"""Native ITK fixture utilities shared by recipes, outside the installed evaluator.

Other software may use its own runtime and emit the same bundle contract.
"""

import argparse
import shutil
import subprocess
from pathlib import Path

import numpy as np
import SimpleITK as sitk

from brainhops_eval.files import digest, inventory, read_json, verify, write_json


def read_image(path):
    path = Path(path)
    return sitk.ReadImage(str(path), sitk.sitkFloat32)


def model_array(image):
    """ITK arrays are z,y,x or y,x; fixture arrays use x,y,z or x,y."""
    return sitk.GetArrayFromImage(image).transpose()


def geometry(image):
    return {"size": list(image.GetSize()), "spacing": list(image.GetSpacing()),
            "origin": list(image.GetOrigin()), "direction": list(image.GetDirection())}


def valid_mask(moving, reference, transform, degree):
    array = np.ones(tuple(reversed(moving.GetSize())), dtype=np.uint8)
    # Exclude the interpolation edge, where package boundary rules can differ.
    if degree:
        for axis in range(array.ndim):
            index = [slice(None)] * array.ndim
            for edge in (0, -1):
                index[axis] = edge
                array[tuple(index)] = 0
    mask = sitk.GetImageFromArray(array)
    mask.CopyInformation(moving)
    return sitk.Resample(mask, reference, transform, sitk.sitkNearestNeighbor, 0, sitk.sitkUInt8)


def command(arguments, log):
    result = subprocess.run(arguments, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    with Path(log).open("a") as stream:
        stream.write(repr(arguments) + "\n" + result.stdout + "\n")
    result.check_returncode()


def affine_from_matrix(matrix):
    matrix = np.asarray(matrix)
    ndim = matrix.shape[0] - 1
    transform = sitk.AffineTransform(ndim)
    transform.SetMatrix(matrix[:ndim, :ndim].ravel().tolist())
    transform.SetTranslation(matrix[:ndim, ndim].tolist())
    return transform


def build(inputs, output, *, backend, register, apply_image, include_rasters=False, container_image=None):
    inputs, output = Path(inputs).resolve(), Path(output).resolve()
    verify(inputs, read_json(inputs / "manifest.json"))
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use an empty output directory to avoid stale fixtures")
    output.mkdir(parents=True, exist_ok=True)
    shutil.copytree(inputs, output / "inputs")
    transforms = output / "transforms"
    transforms.mkdir()
    sitk.ProcessObject.SetGlobalDefaultNumberOfThreads(1)
    registered_path = transforms / "registered.tfm"
    estimated, registration, native_formats = register(inputs, transforms, output)
    sitk.WriteTransform(estimated, str(registered_path))

    landmarks = read_json(inputs / "landmarks.json")
    flip = np.diag([-1., -1., 1., 1.])
    known = affine_from_matrix(flip @ np.linalg.inv(landmarks["push_moving_to_fixed_ras"]) @ flip)
    fixed_lps = np.array(landmarks["fixed"]) * [-1, -1, 1]
    moving_lps = np.array(landmarks["moving"]) * [-1, -1, 1]
    observed = np.array([estimated.TransformPoint(tuple(point)) for point in fixed_lps])
    registration["landmark_error_mm"] = np.linalg.norm(observed - moving_lps, axis=1).tolist()
    write_json(output / "registration.json", {"backend": backend,
               "simpleitk_version": sitk.Version_VersionString(),
               "container_sha256": digest(container_image) if container_image else None,
               "threads": 1, "registration": registration})

    definitions = read_json(inputs / "inputs.json")["variants"]
    cases = []
    for mode, transform in [("known", known),
                            ("registered", estimated)]:
        formats = {"tfm": None, "h5": None}
        if mode == "registered":
            formats.update(native_formats)
        for extension, native_file in formats.items():
            transform_path = transforms / f"{mode}.{extension}"
            if native_file is not None:
                shutil.copyfile(native_file, transform_path)
            else:
                sitk.WriteTransform(transform, str(transform_path))
            converted = sitk.ReadTransform(str(transform_path))
            conversion_error = max(np.linalg.norm(np.array(converted.TransformPoint(tuple(p))) - transform.TransformPoint(tuple(p))) for p in fixed_lps)
            if conversion_error > 1e-8:
                raise ValueError(f"Transform conversion changed points: {transform_path}")
            for variant in definitions:
                case = dict(variant, id=f"{mode}-{extension}-{variant['id']}", kind="nifti")
                case["moving"] = "inputs/" + variant["moving"]
                case["reference"] = "inputs/" + variant["reference"]
                case["transform"] = str(transform_path.relative_to(output))
                case["conversion_max_error_mm"] = float(conversion_error)
                case_dir = output / "cases" / case["id"]
                case_dir.mkdir(parents=True)
                src, ref = read_image(output / case["moving"]), read_image(output / case["reference"])
                apply_image(output / case["moving"], output / case["reference"],
                            transform_path, case["degree"], case_dir / "expected.nii.gz",
                            output / "commands.log")
                np.save(case_dir / "interior.npy", model_array(valid_mask(src, ref, converted, case["degree"])).astype(bool))
                case["expected"] = str((case_dir / "expected.nii.gz").relative_to(output))
                case["mask"] = str((case_dir / "interior.npy").relative_to(output))
                cases.append(case)

    # A recipe opts into raster probes only when it owns that reader path.
    probes = {}
    if include_rasters:
        for extension in ("png",):
            src = read_image(inputs / f"moving.{extension}")
            ref = read_image(inputs / f"fixed.{extension}")
            probes[extension] = {"moving": geometry(src), "reference": geometry(ref)}
            transform = affine_from_matrix(read_json(inputs / "raster-transform.json")["pull_reference_to_moving_xy"])
            transform_path = transforms / f"raster-{extension}.tfm"
            sitk.WriteTransform(transform, str(transform_path))
            case_dir = output / "cases" / extension
            case_dir.mkdir(parents=True)
            result = sitk.Resample(src, ref, transform, sitk.sitkLinear, 0, sitk.sitkFloat32)
            np.save(case_dir / "expected.npy", model_array(result))
            np.save(case_dir / "interior.npy", model_array(valid_mask(src, ref, transform, 1)).astype(bool))
            cases.append({"id": extension, "kind": extension, "degree": 1,
                          "moving": f"inputs/moving.{extension}", "reference": f"inputs/fixed.{extension}",
                          "transform": str(transform_path.relative_to(output)),
                          "expected": f"cases/{extension}/expected.npy", "mask": f"cases/{extension}/interior.npy",
                          "geometry_policy": "simpleitk-default"})
    write_json(output / "geometry-probes.json", probes)
    write_json(output / "cases.json", {"schema_version": 1, "backend": backend,
               "transform_convention": "pull: reference physical LPS to moving physical LPS",
               "boundary": "zero; interpolation-edge differences reported separately",
               "cases": cases})
    write_json(output / "manifest.json", {"schema_version": 1, "files": inventory(output)})
    from software._shared.boundaries import probe

    def write_probe(path, pull, moving, reference):
        sitk.WriteTransform(affine_from_matrix(pull), str(path))
        return path

    probe(output, backend, write_probe, apply_image, extension='tfm')
    return output


def main(generate):
    """Common flags for these ITK-based recipes, not a software registry."""
    parser = argparse.ArgumentParser(description=generate.__doc__)
    parser.add_argument("--inputs", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--container-image", help="Record the generating SIF checksum")
    generate(**vars(parser.parse_args()))
