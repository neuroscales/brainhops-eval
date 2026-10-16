import numpy as np
import pytest

from brainhops_eval.evaluate import compare, reference_in_output_dtype
from brainhops_eval.comparison import assess, conclude


def test_signed_rounding_and_saturation():
    reference = np.array([-200, -2.5, -1.5, -0.5, 0.5, 1.5, 2.5, 200.])
    converted = reference_in_output_dtype(reference, np.int8)
    np.testing.assert_array_equal(converted, [-128, -3, -2, -1, 1, 2, 3, 127])
    assert converted.dtype == np.int8
    np.testing.assert_array_equal(reference, [-200, -2.5, -1.5, -0.5, 0.5, 1.5, 2.5, 200.])


def test_unsigned_conversion_does_not_wrap_or_truncate():
    converted = reference_in_output_dtype(np.array([-4., 0.4, 0.5, 254.6, 300.]), np.uint8)
    np.testing.assert_array_equal(converted, [0, 0, 1, 255, 255])


def test_float_reference_uses_output_precision():
    converted = reference_in_output_dtype(np.array([1.00001, 1.5], np.float64), np.float16)
    assert converted.dtype == np.float16
    np.testing.assert_array_equal(converted, [1., 1.5])


def test_output_comparison_still_detects_a_one_unit_error():
    expected = reference_in_output_dtype(np.array([[1.5, 4.5]]), np.int16)
    actual = np.array([[2, 6]], dtype=np.int16)
    passed, metrics = compare(actual, expected, np.ones_like(actual, dtype=bool), atol=0, nrmse_limit=0)
    assert not passed and metrics["interior_max_abs"] == 1


def test_expected_quantization_is_not_an_interpolation_failure():
    reference = np.array([[1.5, 4.5]])
    actual = np.array([[2, 5]], dtype=np.int16)
    mask = np.ones_like(actual, dtype=bool)
    assert not compare(actual, reference, mask)[0]
    converted = reference_in_output_dtype(reference, actual.dtype)
    assert compare(actual, converted, mask, atol=0, nrmse_limit=0)[0]


def test_nonfinite_reference_cannot_be_hidden_by_integer_cast():
    with pytest.raises(ValueError, match="Non-finite"):
        reference_in_output_dtype(np.array([np.nan]), np.int16)


@pytest.mark.parametrize("dtype", [np.int8, np.uint8, np.int16, np.uint16, np.int64, np.uint64])
@pytest.mark.parametrize("degree", [0, 1])
def test_one_unit_integer_differences_warn_even_when_every_voxel_differs(dtype, degree):
    """Neither signedness, label interpolation nor mismatch frequency changes severity."""
    expected = np.array([1, 3, 8, 12], dtype=dtype)
    actual = np.array([0, 4, 7, 13], dtype=dtype)
    record, converted = assess(actual, expected, np.ones(4, bool), degree)
    conclude(record)
    assert record['status'] == 'warning' and record['interior_passed']
    assert record['metrics']['interior_mismatch_count'] == 4
    assert record['metrics']['interior_nrmse'] > 2e-5
    assert record['diagnostics'][0]['code'] == 'integer-quantization'
    assert record['warnings'] and not record['metrics']['boundary_warning']
    np.testing.assert_array_equal(converted, expected)


def test_integer_warning_does_not_hide_larger_error_or_axis_failure():
    """A single two-unit interior difference still blocks the evaluation."""
    actual = np.array([1, 1, 1, 2], np.int16)
    record, _ = assess(actual, np.zeros(4), np.ones(4, bool), 1)
    conclude(record)
    assert record['status'] == 'fail' and not record['interior_passed']
    assert record['metrics']['interior_max_abs'] == 2
    record, _ = assess(np.ones(4, np.int16), np.zeros(4), np.ones(4, bool), 1)
    record['axis_interpretation'] = {'moving': {'checks': {'pixels_match': False}}}
    conclude(record)
    assert record['status'] == 'fail'


def test_exact_integer_match_passes_and_boolean_mismatch_fails():
    """A warning requires a discrepancy, and Boolean labels retain exact equality."""
    record, _ = assess(np.zeros(4, np.int16), np.zeros(4), np.ones(4, bool), 1)
    conclude(record)
    assert record['status'] == 'pass'
    record, _ = assess(np.ones(4, bool), np.zeros(4), np.ones(4, bool), 1)
    conclude(record)
    assert record['status'] == 'fail'


def test_unsigned_endpoints_do_not_wrap_and_int64_units_are_detected():
    """Measure integer differences before converting them to floating metrics."""
    actual = np.array([0, 255], np.uint8)
    record, _ = assess(actual, np.array([255, 0], np.uint8), np.ones(2, bool), 1)
    conclude(record)
    assert record['status'] == 'fail' and record['metrics']['interior_max_abs'] == 255
    for dtype in (np.int64, np.uint64):
        maximum = np.iinfo(dtype).max
        actual = np.array([maximum - 1, maximum - 2], dtype)
        expected = np.array([maximum, maximum], dtype)
        passed, metrics = compare(actual, expected, np.ones(2, bool), atol=1, nrmse_limit=None)
        assert not passed and metrics['interior_max_abs'] == 2


def test_one_unit_boundary_difference_still_warns():
    """Boundary discrepancies remain visible without blocking interior agreement."""
    record, _ = assess(np.array([0, 1], np.int16), np.zeros(2), np.array([True, False]), 1)
    conclude(record)
    assert record['status'] == 'warning' and record['metrics']['boundary_warning']
