"""Numerical acceptance rules and explicit explanations of each result."""

import numpy as np

from .types import Array, Record


def reference_in_output_dtype(expected: Array, dtype: np.dtype | str) -> Array:
    """Convert reference values only; never alter loaded brainhops images.

    Integer output follows the resampler's round-half-away-from-zero and
    saturation convention, rather than NumPy's truncating integer cast.
    """
    if not np.isfinite(expected).all():
        raise ValueError("Non-finite reference values")
    dtype = np.dtype(dtype)
    if dtype.kind in "iu":
        values = np.asarray(expected, dtype=np.longdouble)
        rounded = np.where(values >= 0, np.floor(values + 0.5), np.ceil(values - 0.5))
        bounds = np.iinfo(dtype)
        return np.clip(rounded, np.longdouble(bounds.min), np.longdouble(bounds.max)).astype(dtype)
    if dtype.kind == "b":
        return np.trunc(expected).astype(dtype)
    if dtype.kind == "f":
        return expected.astype(dtype)
    raise ValueError(f"Unsupported output dtype: {dtype}")


def compare(
    actual: Array,
    expected: Array,
    mask: Array,
    atol: float = 0.02,
    nrmse_limit: float | None = 2e-5,
) -> tuple[bool, Record]:
    """Compare the declared interior; measure the excluded boundary separately.

    Both interior maximum absolute error and NRMSE must satisfy their limits.
    A None NRMSE limit makes that metric informational, as for integer outputs.
    NRMSE is normalised by the reference dynamic range (at least one).
    Boundary discrepancies never change interior acceptance.
    """
    if actual.shape != expected.shape or mask.shape != expected.shape:
        raise ValueError("Output, expectation, and mask shapes must match")
    if not np.isfinite(actual).all() or not np.isfinite(expected).all():
        raise ValueError("Non-finite image values")
    fraction = float(mask.mean())
    if fraction < 0.05:
        raise ValueError(f"Insufficient interior overlap: {fraction:.2%}")
    if actual.dtype.kind in "iu" and expected.dtype == actual.dtype:
        left, right = actual.astype(np.uint64), expected.astype(np.uint64)
        # Unsigned subtraction preserves unit differences even for int64 extremes.
        error = np.where(actual >= expected, left - right, right - left).astype(float)
    else:
        error = np.abs(actual.astype(float) - expected)
    span = max(float(expected.max()) - float(expected.min()), 1)
    maximum = float(error[mask].max())
    nrmse = float(np.sqrt(np.mean(error[mask] ** 2)) / span)
    boundary_maximum = float(error[~mask].max()) if (~mask).any() else 0
    boundary_nrmse = float(np.sqrt(np.mean(error[~mask] ** 2)) / span) if (~mask).any() else 0
    boundary_warning = boundary_maximum > atol or (
        nrmse_limit is not None and boundary_nrmse > nrmse_limit
    )
    metrics = {
        "interior_fraction": fraction,
        "interior_max_abs": maximum,
        "interior_nrmse": nrmse,
        "boundary_max_abs": boundary_maximum,
        "boundary_nrmse": boundary_nrmse,
        "boundary_warning": boundary_warning,
        "all_voxels_rmse": float(np.sqrt(np.mean(error**2))),
        "atol": atol,
        "nrmse_limit": nrmse_limit,
    }
    return maximum <= atol and (nrmse_limit is None or nrmse <= nrmse_limit), metrics


def assess(actual: Array, expected: Array, mask: Array, degree: int) -> tuple[Record, Array]:
    """Apply output-dtype comparison rules and return metrics plus panel values."""
    _, raw = compare(actual, expected, mask, atol=1e-5 if degree == 0 else 0.02)
    converted = reference_in_output_dtype(expected, actual.dtype)
    integer = actual.dtype.kind in "iu"
    discrete = integer or actual.dtype.kind == "b"
    atol, nrmse_limit = (1e-5 if degree == 0 else 0.02), 2e-5
    if discrete:
        atol, nrmse_limit = (1, None) if integer else (0, 0)
    passed, metrics = compare(actual, converted, mask, atol=atol, nrmse_limit=nrmse_limit)
    if discrete:
        metrics["interior_mismatch_count"] = int(np.count_nonzero(actual[mask] != converted[mask]))
        metrics["boundary_mismatch_count"] = int(
            np.count_nonzero(actual[~mask] != converted[~mask])
        )
        metrics["integer_warning"] = bool(integer and passed and metrics["interior_mismatch_count"])
        metrics["boundary_warning"] = bool(metrics["boundary_mismatch_count"])
    metrics["interior_voxel_count"] = int(mask.sum())
    metrics["boundary_voxel_count"] = int((~mask).sum())
    return dict(
        interior_passed=passed,
        metrics=metrics,
        raw_reference_metrics=raw,
        comparison_dtype=str(actual.dtype),
        comparison_policy=(
            "Reference converted to decoded brainhops output dtype; integer differences "
            "of one unit warn, larger interior differences fail. Boolean equality is exact."
        ),
    ), converted


def _integer_diagnostic(record: Record) -> Record:
    """Describe integer disagreement with its maximum error and warning threshold."""
    metrics = record["metrics"]
    warning = metrics.get("integer_warning", False)
    limit, maximum = metrics["atol"], metrics["interior_max_abs"]
    summary = (
        f"{metrics['interior_mismatch_count']:,} of "
        f"{metrics['interior_voxel_count']:,} interior voxels differ"
    )
    if limit:
        summary += (
            f" in {record['comparison_dtype']} (maximum {maximum:g} intensity units); "
            f"differences up to {limit:g} unit only warn."
        )
    else:
        summary += f"; exact {record['comparison_dtype']} equality is required."
    return dict(
        code="integer-quantization" if warning else "integer-mismatch",
        scope="interior",
        severity="warning" if warning else "failure",
        summary=summary,
        observed=maximum,
        limit=limit,
    )


def explain(record: Record) -> list[Record]:
    """Explain numerical, axis and boundary outcomes without guessing root causes."""
    metrics = record["metrics"]
    reasons: list[Record] = []
    mismatches = metrics.get("interior_mismatch_count", 0)
    if mismatches:
        reasons.append(_integer_diagnostic(record))
    if not mismatches and metrics["interior_max_abs"] > metrics["atol"]:
        reasons.append(
            dict(
                code="max-absolute-error",
                scope="interior",
                summary=f"Interior maximum absolute error {metrics['interior_max_abs']:.6g} exceeds {metrics['atol']:.6g}.",
                observed=metrics["interior_max_abs"],
                limit=metrics["atol"],
            )
        )
    if not mismatches and metrics["nrmse_limit"] is not None and metrics["interior_nrmse"] > metrics["nrmse_limit"]:
        reasons.append(
            dict(
                code="normalised-rmse",
                scope="interior",
                summary=f"Interior NRMSE {metrics['interior_nrmse']:.6g} exceeds {metrics['nrmse_limit']:.6g}.",
                observed=metrics["interior_nrmse"],
                limit=metrics["nrmse_limit"],
            )
        )
    for role, interpretation in record.get("axis_interpretation", {}).items():
        for name, passed in interpretation["checks"].items():
            if not passed:
                reasons.append(
                    dict(
                        code="axis-interpretation",
                        scope="axes",
                        summary=f"{role.capitalize()} image: {name.replace('_', ' ')} failed.",
                    )
                )
    if metrics["boundary_warning"]:
        reasons.append(
            dict(
                code="boundary-difference",
                scope="boundary",
                summary=f"Boundary differences exceed comparison thresholds (max absolute error {metrics['boundary_max_abs']:.6g}); boundary values do not affect acceptance.",
            )
        )
    return reasons


def conclude(record: Record) -> None:
    """Explain failures and nonblocking boundary or integer quantization warnings."""
    record["diagnostics"] = explain(record)
    failures = [reason for reason in record["diagnostics"] if reason["scope"] != "boundary" and reason.get("severity") != "warning"]
    status = (
        "fail" if failures else ("warning" if record["diagnostics"] else "pass")
    )
    record["status"] = status
    record["summary"] = (
        " ".join(reason["summary"] for reason in record["diagnostics"])
        or "Interior and boundary comparisons satisfy all thresholds."
    )
    record.setdefault("warnings", []).extend(
        reason["summary"] for reason in record["diagnostics"] if reason["scope"] == "boundary" or reason.get("severity") == "warning"
    )
