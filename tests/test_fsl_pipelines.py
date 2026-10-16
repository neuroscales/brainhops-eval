"""FSL comparisons retain both the spline and native rasterization paths."""

from copy import deepcopy

import pytest

from brainhops_eval.evaluate import _initial_record
from brainhops_eval.files import read_json, verify, write_json
from brainhops_eval.report import _metadata
from software.fsl.pipelines import append_rebased_cases


def test_rebased_warp_uses_variant_frames_and_keeps_original_comparison(tmp_path):
    """Do not reuse the original coefficient image frames for a rebased field."""
    case = dict(
        id="nonlinear-spline-oblique",
        kind="nifti",
        degree=1,
        transform="coefficients.nii.gz",
        transform_hint="fnirt",
        transform_family="bspline-order3-with-affine",
        transform_images={"moving": "original-moving.nii", "reference": "original-fixed.nii"},
        moving="variant-moving.nii",
        reference="oblique-reference.nii",
        expected="cases/spline/expected.nii.gz",
        mask="cases/spline/interior.npy",
        max_abs=0.02,
    )
    original = deepcopy(case)
    folder = tmp_path / "cases/spline"
    folder.mkdir(parents=True)
    (folder / "expected-rebased.nii.gz").write_bytes(b"native-warp")
    write_json(tmp_path / "cases.json", {"cases": [case]})
    write_json(tmp_path / "coverage.json", {"tested": [], "unavailable": []})

    append_rebased_cases(tmp_path)

    direct, exact = read_json(tmp_path / "cases.json")["cases"]
    assert all(direct[key] == value for key, value in original.items())
    assert exact["transform"] == "cases/spline/expected-rebased.nii.gz"
    assert exact["transform_images"] == {"moving": case["moving"], "reference": case["reference"]}
    assert exact["transform_options"] == {"deformation_type": "relative"}
    assert exact["expected"] == direct["expected"]
    assert exact["mask"] == direct["mask"]
    assert exact["max_abs"] == direct["max_abs"]
    assert (folder / "expected-rebased.nii.gz").read_bytes() == b"native-warp"
    verify(tmp_path, read_json(tmp_path / "manifest.json"))
    assert read_json(tmp_path / "coverage.json")["tested"][0]["cases"] == [exact["id"]]
    record = _initial_record(direct, "fsl", "python")
    html = _metadata(record)
    assert "convertwarp rasterization" in html
    assert "original coefficient spline directly" in html
    assert "Acceptance thresholds are unchanged" in html


def test_missing_native_warp_is_not_substituted(tmp_path):
    """Refuse a missing native input instead of synthesizing a replacement."""
    write_json(
        tmp_path / "cases.json",
        {"cases": [{"transform_family": "bspline-order2", "expected": "expected.nii.gz"}]},
    )
    write_json(tmp_path / "coverage.json", {"tested": []})
    with pytest.raises(FileNotFoundError, match="Missing native applywarp input"):
        append_rebased_cases(tmp_path)
