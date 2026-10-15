"""Explicit package geometry for formats without an anatomical world frame.

This is evaluation-side glue, not a change to brainhops reader defaults.
The target coordinate system is supplied by the package-native transform.
"""

import numpy as np


def with_package_geometry(data, geometry, world):
    from brainhops.datamodel.axes import Axis
    from brainhops.datamodel.images import SingleScaleImage
    from brainhops.datamodel.systems import ArrayCoordinateSystem
    from brainhops.datamodel.transformations import Affine

    ndim = data.ndim
    if list(data.shape) != geometry["size"]:
        raise ValueError("Model array shape does not match the package geometry probe")
    voxel = ArrayCoordinateSystem(axes=[
        Axis(name=name, type="space", unit="index") for name in "xyz"[:ndim]
    ])
    matrix = np.zeros((ndim, ndim + 1))
    matrix[:, :ndim] = np.array(geometry["direction"]).reshape(ndim, ndim) @ np.diag(geometry["spacing"])
    matrix[:, ndim] = geometry["origin"]
    return SingleScaleImage(data=data, transformations=[Affine(input=voxel, output=world, matrix=matrix)])

