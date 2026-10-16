"""Run reg_aladin and resample with reg_resample's physical RAS pull map."""

import os

import numpy as np

from software._shared.affine import build, command, main


def write_transform(path, pull, moving, reference):
    np.savetxt(path, pull, fmt="%.15g")
    return path


def register(moving, reference, transforms, log):
    path = transforms / "registered.txt"
    version = command(["reg_aladin", "--version"], log)
    command(["reg_aladin", "-ref", reference, "-flo", moving, "-aff", path,
             "-res", transforms / "registered.nii.gz", "-ln", "3", "-lp", "3",
             "-maxit", "10", "-omp", "1"], log)
    return np.loadtxt(path), path, {"version": version, "algorithm": "reg_aladin affine",
                                  "levels": 3, "performed_levels": 3, "max_iterations": 10}


def apply_image(moving, reference, transform, degree, output, log):
    command(["reg_resample", "-ref", reference, "-flo", moving, "-trans", transform,
             "-res", output, "-inter", str(degree), "-pad", "0", "-omp", "1"], log)


def generate(inputs, output, container_image=None):
    os.environ["OMP_NUM_THREADS"] = "1"
    result = build(inputs, output, backend="niftyreg", register=register,
                 write_transform=write_transform, apply_image=apply_image, hint="niftyreg.aladin",
                 convention="reg_aladin affine: reference world RAS mm to floating world RAS mm (pull)",
                 container_image=container_image)
    from software.niftyreg.nonlinear import append
    return append(result)


if __name__ == "__main__":
    main(generate)
