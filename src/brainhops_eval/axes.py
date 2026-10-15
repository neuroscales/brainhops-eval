"""Inspect loaded raster axes against native package probes without adapting them."""

from pathlib import Path

import numpy as np
from PIL import Image


def raster_axis_check(image, path, package_geometry):
    from brainhops.datamodel.transformations import Affine

    path = Path(path)
    if path.suffix == ".npy":
        storage = np.load(path, allow_pickle=False)
    else:
        with Image.open(path) as raster:
            storage = np.asarray(raster)
    # SimpleITK reads these scalar fixtures as rows,columns in storage and
    # x,y in its model. This is independent reference data, never an edit
    # or transpose of the image returned by brainhops.
    expected_data = storage.T
    actual_data = np.asarray(image.data)
    ndim = len(package_geometry["size"])
    expected_matrix = np.column_stack([
        np.array(package_geometry["direction"]).reshape(ndim, ndim)
        @ np.diag(package_geometry["spacing"]),
        package_geometry["origin"],
    ])
    transformation = image.transformation
    actual_matrix = np.asarray(transformation.to(Affine).matrix)
    checks = {
        "shape_matches_package": list(actual_data.shape) == package_geometry["size"],
        "pixels_match_package_axis_order": bool(np.array_equal(actual_data, expected_data)),
        "numeric_grid_matches_package": bool(
            actual_matrix.shape == expected_matrix.shape
            and np.allclose(actual_matrix, expected_matrix, atol=1e-6, rtol=1e-6)
        ),
    }

    def describe_axes(system):
        return [{"name": str(getattr(axis, "name", None)),
                 "type": str(getattr(axis, "type", None)),
                 "unit": str(getattr(axis, "unit", None)),
                 "orientation": str(getattr(axis, "orientation", None))}
                for axis in system.axes]

    return {
        "passed": all(checks.values()), "checks": checks,
        "storage_shape": list(storage.shape),
        "loaded_shape": list(actual_data.shape),
        "package_geometry": package_geometry,
        "loaded_grid_to_model": actual_matrix.tolist(),
        "package_grid_to_model": expected_matrix.tolist(),
        "loaded_grid_axes": describe_axes(transformation.input),
        "loaded_model_axes": describe_axes(transformation.output),
        "scope": "Numeric grid and pixel order; unspecified anatomical orientations are not inferred.",
    }

