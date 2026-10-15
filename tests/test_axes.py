from copy import deepcopy

import brainhops.io as bio

from brainhops_eval.axes import raster_axis_check
from brainhops_eval.files import read_json


def test_raster_axes_match_independent_native_probe(fixtures):
    path = fixtures / "inputs/moving.png"
    image = bio.images.load(path)
    probe = read_json(fixtures / "geometry-probes.json")["png"]["moving"]
    result = raster_axis_check(image, path, probe)
    assert result["passed"]
    assert result["storage_shape"] == [47, 63]
    assert result["loaded_shape"] == [63, 47]


def test_axis_checks_detect_swapped_dimensions_and_flipped_direction(fixtures):
    path = fixtures / "inputs/moving.png"
    image = bio.images.load(path)
    probe = read_json(fixtures / "geometry-probes.json")["png"]["moving"]
    swapped = deepcopy(probe)
    swapped["size"] = swapped["size"][::-1]
    assert not raster_axis_check(image, path, swapped)["checks"]["shape_matches_package"]
    flipped = deepcopy(probe)
    flipped["direction"][0] *= -1
    assert not raster_axis_check(image, path, flipped)["checks"]["numeric_grid_matches_package"]
