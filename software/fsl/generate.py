"""Run FLIRT and apply its affine in FSL's scaled-mm convention."""

import os
from pathlib import Path

import numpy as np

from software._shared.affine import build, command, flirt_from_pull, main, pull_from_flirt


def write_transform(path, pull, moving, reference):
    np.savetxt(path, flirt_from_pull(pull, moving, reference), fmt="%.15g")
    return path


def register(moving, reference, transforms, log):
    path = transforms / "registered.mat"
    version = command(["flirt", "-version"], log)
    arguments = ["flirt", "-in", moving, "-ref", reference, "-omat", path,
                 "-out", transforms / "registered.nii.gz", "-dof", "12", "-cost", "leastsq",
                 "-searchrx", "-15", "15", "-searchry", "-15", "15", "-searchrz", "-15", "15"]
    command(arguments, log)
    return pull_from_flirt(np.loadtxt(path), moving, reference), path, {
        "version": version, "fsl_build": (Path(os.environ["FSLDIR"]) / "etc/fslversion").read_text().strip(), "algorithm": "FLIRT affine", "dof": 12, "cost": "leastsq",
        "search_degrees": [-15, 15]}


def apply_image(moving, reference, transform, degree, output, log):
    command(["flirt", "-in", moving, "-ref", reference, "-applyxfm", "-init", transform,
             "-interp", "trilinear" if degree else "nearestneighbour", "-datatype", "float",
             "-out", output], log)


def generate(inputs, output, container_image=None):
    os.environ.update(FSLOUTPUTTYPE="NIFTI_GZ", OMP_NUM_THREADS="1")
    result = build(inputs, output, backend="fsl", register=register, write_transform=write_transform,
                 apply_image=apply_image, hint="flirt", image_options=True,
                 convention="FLIRT moving scaled-mm to reference scaled-mm; decoded as RAS pull using original images",
                 container_image=container_image)
    from software.fsl.nonlinear import append
    return append(result)


if __name__ == "__main__":
    main(generate)
