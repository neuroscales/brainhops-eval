"""Reference runner; requires SimpleITK, never brainhops."""

import shutil
import subprocess
from pathlib import Path

import nibabel as nib
import numpy as np
import SimpleITK as sitk

from ..files import digest, inventory, read_json, verify, write_json


def read_image(path):
    path = Path(path)
    if path.suffix == ".npy":
        return sitk.Cast(sitk.GetImageFromArray(np.load(path, allow_pickle=False)), sitk.sitkFloat32)
    return sitk.ReadImage(str(path), sitk.sitkFloat32)


def model_array(image):
    """ITK arrays are z,y,x or y,x; fixture arrays use x,y,z or x,y."""
    return sitk.GetArrayFromImage(image).transpose()


def geometry(image):
    return {"size": list(image.GetSize()), "spacing": list(image.GetSpacing()),
            "origin": list(image.GetOrigin()), "direction": list(image.GetDirection())}


def register(fixed, moving):
    initial = sitk.CenteredTransformInitializer(
        fixed, moving, sitk.Euler3DTransform(),
        sitk.CenteredTransformInitializerFilter.GEOMETRY,
    )
    method = sitk.ImageRegistrationMethod()
    method.SetMetricAsMeanSquares()
    method.SetMetricSamplingStrategy(method.NONE)
    method.SetInterpolator(sitk.sitkLinear)
    method.SetOptimizerAsRegularStepGradientDescent(
        learningRate=1, minStep=0.001, numberOfIterations=120,
        gradientMagnitudeTolerance=1e-6,
    )
    method.SetOptimizerScalesFromPhysicalShift()
    method.SetShrinkFactorsPerLevel([2, 1])
    method.SetSmoothingSigmasPerLevel([1, 0])
    method.SmoothingSigmasAreSpecifiedInPhysicalUnitsOn()
    method.SetInitialTransform(initial, inPlace=True)
    method.Execute(fixed, moving)
    # Flatten rigid output into an affine to exercise broad file interoperability.
    affine = sitk.AffineTransform(3)
    affine.SetCenter(initial.GetCenter())
    affine.SetMatrix(initial.GetMatrix())
    affine.SetTranslation(initial.GetTranslation())
    return affine, {"metric": method.GetMetricValue(),
                    "stop_condition": method.GetOptimizerStopConditionDescription(),
                    "optimizer": "RegularStepGradientDescent", "iterations": 120,
                    "metric_name": "MeanSquares", "shrink_factors": [2, 1],
                    "smoothing_sigmas_mm": [1, 0], "sampling": "all voxels"}


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


def build(inputs, output, backend="simpleitk"):
    inputs, output = Path(inputs).resolve(), Path(output).resolve()
    verify(inputs, read_json(inputs / "manifest.json"))
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use an empty output directory to avoid stale fixtures")
    output.mkdir(parents=True, exist_ok=True)
    shutil.copytree(inputs, output / "inputs")
    transforms = output / "transforms"
    transforms.mkdir()
    sitk.ProcessObject.SetGlobalDefaultNumberOfThreads(1)
    fixed = read_image(inputs / "fixed.nii.gz")
    moving = read_image(inputs / "moving.nii.gz")
    registered_path = transforms / "registered.tfm"
    if backend == "simpleitk":
        estimated, registration = register(fixed, moving)
        sitk.WriteTransform(estimated, str(registered_path))
    elif backend == "ants":
        prefix = str(transforms / "ants-")
        # Fixed seed and one thread are also set in the container environment.
        command([
            "antsRegistration", "--dimensionality", "3", "--float", "1",
            "--output", prefix, "--interpolation", "Linear",
            "--initial-moving-transform", f"[{inputs / 'fixed.nii.gz'},{inputs / 'moving.nii.gz'},0]",
            "--transform", "Rigid[0.1]",
            "--metric", f"MeanSquares[{inputs / 'fixed.nii.gz'},{inputs / 'moving.nii.gz'},1,0]",
            "--convergence", "[120x60,1e-6,10]",
            "--shrink-factors", "2x1", "--smoothing-sigmas", "1x0mm",
            "--random-seed", "1729",
        ], output / "commands.log")
        estimated = sitk.ReadTransform(prefix + "0GenericAffine.mat")
        sitk.WriteTransform(estimated, str(registered_path))
        registration = {"native_transform": "transforms/ants-0GenericAffine.mat",
                        "commands": "commands.log", "seed": 1729}
        version = subprocess.run(["antsRegistration", "--version"], capture_output=True, text=True, check=True)
        registration["version"] = version.stdout.strip()
    else:
        raise ValueError(f"Unknown backend: {backend}")

    landmarks = read_json(inputs / "landmarks.json")
    fixed_lps = np.array(landmarks["fixed"]) * [-1, -1, 1]
    moving_lps = np.array(landmarks["moving"]) * [-1, -1, 1]
    observed = np.array([estimated.TransformPoint(tuple(point)) for point in fixed_lps])
    registration["landmark_error_mm"] = np.linalg.norm(observed - moving_lps, axis=1).tolist()
    write_json(output / "registration.json", {"backend": backend,
               "simpleitk_version": sitk.Version_VersionString(),
               "threads": 1, "registration": registration})

    definitions = read_json(inputs / "inputs.json")["variants"]
    cases = []
    for mode, transform in [("known", sitk.ReadTransform(str(inputs / "known-pull.tfm"))),
                            ("registered", estimated)]:
        formats = ["tfm", "h5"]
        if backend == "ants" and mode == "registered":
            formats.append("mat")
        for extension in formats:
            transform_path = transforms / f"{mode}.{extension}"
            if extension == "mat":
                shutil.copyfile(transforms / "ants-0GenericAffine.mat", transform_path)
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
                if backend == "ants":
                    command(["antsApplyTransforms", "-d", "3", "--float", "1",
                             "-i", str(output / case["moving"]), "-r", str(output / case["reference"]),
                             "-t", str(transform_path), "-n", "NearestNeighbor" if not case["degree"] else "Linear",
                             "-o", str(case_dir / "expected.nii.gz")], output / "commands.log")
                else:
                    result = sitk.Resample(src, ref, converted,
                                           sitk.sitkLinear if case["degree"] else sitk.sitkNearestNeighbor,
                                           0, sitk.sitkFloat32)
                    sitk.WriteImage(result, str(case_dir / "expected.nii.gz"))
                np.save(case_dir / "interior.npy", model_array(valid_mask(src, ref, converted, case["degree"])).astype(bool))
                case["expected"] = str((case_dir / "expected.nii.gz").relative_to(output))
                case["mask"] = str((case_dir / "interior.npy").relative_to(output))
                cases.append(case)

    # PNG/NPY default-space cases use the SimpleITK reader or GetImageFromArray.
    # ANTs is deliberately not credited with these SimpleITK-only cases.
    probes = {}
    if backend == "simpleitk":
        for extension in ("png", "npy"):
            src = read_image(inputs / f"moving.{extension}")
            ref = read_image(inputs / f"fixed.{extension}")
            probes[extension] = {"moving": geometry(src), "reference": geometry(ref)}
            transform = sitk.ReadTransform(str(inputs / "raster-known-pull.tfm"))
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
    return output

