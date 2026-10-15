import nibabel as nib
import numpy as np
import pytest
import SimpleITK as sitk
from scipy.ndimage import map_coordinates

from brainhops_eval.evaluate import compare, evaluate
from brainhops_eval.files import inventory, read_json, verify, write_json
from brainhops_eval.fixtures import coordinates, generate


def test_deliberately_different_geometry_and_storage(inputs):
    fixed, moving = [nib.load(inputs / name) for name in ("fixed.nii.gz", "moving.nii.gz")]
    assert nib.aff2axcodes(fixed.affine) == ("R", "A", "S")
    assert nib.aff2axcodes(moving.affine) == ("S", "L", "P")
    assert fixed.shape != moving.shape
    assert fixed.get_data_dtype() == np.float32
    assert moving.get_data_dtype() == np.int16
    assert not np.allclose(moving.affine[:3, :3], np.diag(np.diag(moving.affine[:3, :3])))
    low = nib.load(inputs / "moving-downsampled.nii.gz")
    assert np.allclose(low.affine, moving.affine @ np.diag([1.7, 1.7, 1.7, 1]))
    assert all(a < b for a, b in zip(low.shape, moving.shape))
    assert nib.load(inputs / "moving-uint8.nii.gz").get_data_dtype() == np.uint8
    left = nib.load(inputs / "moving-left-handed.nii.gz")
    assert np.linalg.det(left.affine[:3, :3]) * np.linalg.det(moving.affine[:3, :3]) < 0
    np.testing.assert_array_equal(left.get_fdata()[::-1], moving.get_fdata())


def test_generation_is_reproducible(inputs, tmp_path):
    second = generate(tmp_path / "repeat")
    assert inventory(inputs) == inventory(second)


def test_known_transform_maps_independent_landmarks(inputs):
    landmarks = read_json(inputs / "landmarks.json")
    transform = sitk.ReadTransform(str(inputs / "known-pull.tfm"))
    fixed = np.array(landmarks["fixed"]) * [-1, -1, 1]
    got = np.array([transform.TransformPoint(tuple(p)) for p in fixed])
    np.testing.assert_allclose(got, np.array(landmarks["moving"]) * [-1, -1, 1], atol=1e-10)


def test_native_resampling_agrees_with_independent_ras_pull(fixtures):
    """An erroneous LPS/RAS flip or transform direction must fail here."""
    source = nib.load(fixtures / "inputs/moving.nii.gz")
    reference = nib.load(fixtures / "inputs/fixed.nii.gz")
    landmarks = read_json(fixtures / "inputs/landmarks.json")
    push = np.array(landmarks["push_moving_to_fixed_ras"])
    indices = coordinates(reference.shape, np.linalg.inv(source.affine) @ np.linalg.inv(push) @ reference.affine)
    expected = map_coordinates(source.get_fdata(), indices, order=1, mode="constant")
    native = nib.load(fixtures / "cases/known-tfm-native/expected.nii.gz").get_fdata()
    mask = np.load(fixtures / "cases/known-tfm-native/interior.npy")
    np.testing.assert_allclose(native[mask], expected[mask], atol=0.003, rtol=1e-5)
    registration = read_json(fixtures / "registration.json")["registration"]
    assert max(registration["landmark_error_mm"]) < 2


def test_fixture_integrity_detects_tampering(fixtures, tmp_path):
    import shutil
    shutil.copytree(fixtures, tmp_path / "fixtures")
    copy = tmp_path / "fixtures"
    (copy / "inputs/moving.npy").write_bytes(b"modified")
    with pytest.raises(ValueError, match="Checksum mismatch"):
        verify(copy, read_json(copy / "manifest.json"))


def test_full_python_evaluation_and_portable_report(fixtures, tmp_path):
    report = tmp_path / "report"
    assert evaluate(fixtures, report, brainhops_ref="test-ref", brainhops_sha="test-sha")
    result = read_json(report / "results.json")
    assert len(result["cases"]) == 26
    assert result["brainhops_ref"] == "test-ref"
    assert result["brainhops_sha"] == "test-sha"
    assert "test-sha" in (report / "index.html").read_text()
    for case in result["cases"]:
        assert (report / case["preview"]).is_file()


def test_bad_comparison_still_writes_report(fixtures, tmp_path):
    import shutil
    copy = tmp_path / "fixtures"
    shutil.copytree(fixtures, copy)
    cases = read_json(copy / "cases.json")
    cases["cases"] = [case for case in cases["cases"] if case["id"] == "npy"]
    write_json(copy / "cases.json", cases)
    expected_path = copy / "cases/npy/expected.npy"
    np.save(expected_path, np.load(expected_path) + 100)
    write_json(copy / "manifest.json", {"schema_version": 1, "files": inventory(copy)})
    report = tmp_path / "report"
    assert not evaluate(copy, report)
    assert read_json(report / "results.json")["cases"][0]["status"] == "fail"
    assert (report / "index.html").is_file()


@pytest.mark.parametrize("actual,mask", [
    (np.full((3, 4), np.nan), np.ones((3, 4), bool)),
    (np.zeros((3, 4)), np.zeros((3, 4), bool)),
])
def test_invalid_comparisons_cannot_pass(actual, mask):
    with pytest.raises(ValueError):
        compare(actual, np.zeros((3, 4)), mask)

