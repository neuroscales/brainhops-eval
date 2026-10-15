"""Run MRtrix3 affine registration and scanner-space native resampling."""

import os

import numpy as np

from software._shared.affine import build, command, main


def write_transform(path, pull, moving, reference):
    np.savetxt(path, pull, fmt="%.15g", header="command_history: brainhops-eval known physical RAS pull")
    return path


def register(moving, reference, transforms, log):
    path = transforms / "registered.txt"
    version = command(["mrregister", "-version"], log)
    command(["mrregister", moving, reference, "-type", "affine", "-affine", path,
             "-affine_scale", "0.5,1", "-affine_niter", "50,30", "-nthreads", "1"], log)
    return np.loadtxt(path), path, {"version": version, "algorithm": "mrregister affine",
                                  "scales": [0.5, 1], "max_iterations": [50, 30]}


def apply_image(moving, reference, transform, degree, output, log):
    # Disable automatic oversampling: compare interpolants at voxel centres.
    command(["mrtransform", moving, output, "-template", reference, "-linear", transform,
             "-interp", "linear" if degree else "nearest", "-oversample", "1",
             "-datatype", "float32", "-nthreads", "1"], log)


def generate(inputs, output, container_image=None):
    os.environ["OMP_NUM_THREADS"] = "1"
    return build(inputs, output, backend="mrtrix", register=register,
                 write_transform=write_transform, apply_image=apply_image, hint="mrtrix.linear",
                 convention="MRtrix reverse convention: template scanner RAS mm to moving scanner RAS mm (pull)",
                 container_image=container_image)


if __name__ == "__main__":
    main(generate)
