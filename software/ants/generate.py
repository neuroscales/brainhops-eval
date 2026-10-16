"""Generate native ANTs registration and resampling fixtures."""

import subprocess

import SimpleITK as sitk

from software._shared.itk import build, command, main


def register(inputs, transforms, output):
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
    registration = {"native_transform": "transforms/ants-0GenericAffine.mat",
                    "commands": "commands.log", "seed": 1729}
    version = subprocess.run(["antsRegistration", "--version"], capture_output=True, text=True, check=True)
    registration["version"] = version.stdout.strip()
    return estimated, registration, {"mat": transforms / "ants-0GenericAffine.mat"}


def apply_image(source, reference, transform, degree, output, log):
    command(["antsApplyTransforms", "-d", "3", "--float", "1",
             "-i", str(source), "-r", str(reference), "-t", str(transform),
             "-n", "NearestNeighbor" if not degree else "Linear",
             "-o", str(output)], log)


def generate(inputs, output, container_image=None):
    """Generate ANTs references from a shared input bundle."""
    result = build(inputs, output, backend="ants", register=register,
                 apply_image=apply_image, container_image=container_image)
    from software.ants.nonlinear import append
    return append(result)


if __name__ == "__main__":
    main(generate)
