import numpy as np
import pytest

from brainhops_eval.evaluate import compare, reference_in_output_dtype


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
