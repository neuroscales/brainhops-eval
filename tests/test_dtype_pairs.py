"""Dtype comparisons must preserve values, geometry and application settings."""

import nibabel as nib
import numpy as np

from brainhops_eval.files import read_json
from brainhops_eval.report_sections import dtype_pairs


def test_every_integer_volume_has_an_identical_float32_variant(inputs):
    """Match every integer source, including labels, without regridding it."""
    variants = read_json(inputs / "inputs.json")["variants"]
    by_id = {variant["id"]: variant for variant in variants}
    integers = [
        v
        for v in variants
        if np.issubdtype(nib.load(inputs / v["moving"]).get_data_dtype(), np.integer)
    ]
    assert {v["id"] for v in integers} == {
        "native",
        "left-handed",
        "reference-oblique",
        "uint8",
        "int8",
        "labels",
    }
    for integer in integers:
        floating = by_id[integer["id"] + "-float32"]
        assert floating["integer_variant"] == integer["id"]
        assert floating["degree"] == integer["degree"]
        assert floating["display_window"] == integer["display_window"]
        for role in ("moving", "reference"):
            original = nib.load(inputs / integer[role])
            converted = nib.load(inputs / floating[role])
            assert converted.get_data_dtype() == np.float32
            np.testing.assert_array_equal(converted.get_fdata(), original.get_fdata())
            np.testing.assert_array_equal(converted.affine, original.affine)
            np.testing.assert_array_equal(converted.get_qform(), original.get_qform())


def test_native_dtype_pairs_use_the_same_transform_and_mask(fixtures):
    """Native expectations are regenerated, rather than casting integer outputs."""
    cases = read_json(fixtures / "cases.json")["cases"]
    by_id = {case["id"]: case for case in cases}
    pairs = [case for case in cases if case.get("integer_variant")]
    assert len(pairs) == 24
    for floating in pairs:
        integer = by_id[floating["id"].removesuffix("-float32")]
        assert floating["transform"] == integer["transform"]
        assert floating["degree"] == integer["degree"]
        np.testing.assert_array_equal(
            np.load(fixtures / floating["mask"]), np.load(fixtures / integer["mask"])
        )
        expected = nib.load(fixtures / floating["expected"])
        assert expected.get_data_dtype() == np.float32
        np.testing.assert_array_equal(
            expected.get_fdata(), nib.load(fixtures / integer["expected"]).get_fdata()
        )


def test_pair_table_links_both_cases_and_explains_different_thresholds():
    """Show both statuses and numerical errors for a matched application."""
    integer = dict(
        id="case", status="warning", output_dtype="int16", metrics={"interior_max_abs": 1}
    )
    floating = dict(
        id="case-float32",
        integer_counterpart="case",
        status="fail",
        output_dtype="float32",
        metrics={"interior_max_abs": 0.1},
    )
    html = dtype_pairs([integer, floating])
    assert 'href="case/index.html"' in html
    assert 'href="case-float32/index.html"' in html
    assert "int16" in html and "float32" in html
    assert "0.1" in html
    assert "acceptance thresholds differ" in html
