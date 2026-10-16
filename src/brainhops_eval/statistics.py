"""Summarise recorded outcomes without changing their acceptance decisions."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable
from typing import Any

from .types import Record

STATUSES = ("pass", "warning", "fail", "error")
STATUS_LABELS = {
    "pass": "Success",
    "warning": "Warning",
    "fail": "Fail",
    "error": "Error",
    "incomplete": "Incomplete",
}
ISSUE_LABELS = {
    "integer-mismatch": "Integer-value disagreement",
    "integer-quantization": "One-unit integer differences",
    "max-absolute-error": "Interior absolute-error threshold",
    "normalised-rmse": "Interior NRMSE threshold",
    "axis-interpretation": "Axis interpretation",
    "boundary-difference": "Boundary conditions",
    "execution-error": "Reader / application / validation error",
    "unclassified": "Failure without recorded diagnostics",
}
SOFTWARE_NAMES = {
    "simpleitk": "SimpleITK",
    "ants": "ANTs",
    "fsl": "FSL",
    "niftyreg": "NiftyReg",
    "elastix": "elastix",
    "mrtrix": "MRtrix",
}


def software_name(name: str) -> str:
    """Return the native software's conventional display name."""
    return SOFTWARE_NAMES.get(name, name)


def status_counts(cases: list[Record]) -> Record:
    """Count every outcome, retaining explicit zeros for absent statuses."""
    counts = Counter(case["status"] for case in cases)
    return {status: counts[status] for status in STATUSES}


def overall_status(cases: list[Record]) -> str:
    """Keep warnings visible even when all blocking checks pass."""
    counts = status_counts(cases)
    if counts["fail"] or counts["error"]:
        return "fail"
    if counts["warning"]:
        return "warning"
    return "pass" if cases else "incomplete"


def case_summary(case: Record) -> str:
    """Explain a result, including older records without structured diagnostics."""
    if case.get("summary"):
        return str(case["summary"])
    if case.get("error"):
        return case["error"].strip().splitlines()[-1]
    metrics = case.get("metrics", {})
    mismatches = metrics.get("interior_mismatch_count", 0)
    if mismatches:
        return f"{mismatches:,} interior voxels differ; exact integer equality is required."
    if case["status"] == "fail":
        return f"Interior max error {metrics.get('interior_max_abs', '?')} (limit {metrics.get('atol', '?')}); NRMSE {metrics.get('interior_nrmse', '?')} (limit {metrics.get('nrmse_limit', '?')}). Check axis interpretation too."
    return {
        "pass": "Interior and boundary thresholds satisfied.",
        "warning": "Interior passes; boundary conditions differ.",
        "error": "Execution failed before a complete comparison.",
    }.get(case["status"], "No result.")


def issue_codes(case: Record) -> set[str]:
    """Classify observed discrepancies, reconstructing only recorded legacy facts."""
    if case["status"] == "error":
        return {"execution-error"}
    codes = {reason["code"] for reason in case.get("diagnostics", [])}
    metrics = case.get("metrics", {})
    if metrics.get("interior_mismatch_count", 0):
        codes.add("integer-quantization" if metrics.get("integer_warning") else "integer-mismatch")
    for key, limit, code in [
        ("interior_max_abs", "atol", "max-absolute-error"),
        ("interior_nrmse", "nrmse_limit", "normalised-rmse"),
    ]:
        threshold = metrics.get(limit)
        if (
            not metrics.get("interior_mismatch_count")
            and threshold is not None
            and metrics.get(key, 0) > threshold
        ):
            codes.add(code)
    if metrics.get("boundary_warning") or (
        case["status"] == "warning"
        and not case.get("diagnostics")
        and not metrics.get("integer_warning")
    ):
        codes.add("boundary-difference")
    if any(
        not all(item.get("checks", {}).values())
        for item in case.get("axis_interpretation", {}).values()
    ):
        codes.add("axis-interpretation")
    if case["status"] == "fail" and not (codes - {"boundary-difference"}):
        codes.add("unclassified")
    return codes


def issue_counts(cases: list[Record], *, blocking_only: bool = False) -> Record:
    """Count affected cases once per reason; one case can have several reasons."""
    counts: Counter[str] = Counter()
    for case in cases:
        codes = issue_codes(case)
        if blocking_only:
            codes.discard("boundary-difference")
        counts.update(codes)
    return dict(sorted(counts.items(), key=lambda pair: (-pair[1], pair[0])))


def family(case: Record) -> str:
    """Read the actual recorded transform family, including legacy affine cases."""
    return str(case.get("transform_family") or "affine")


def image_kind(case: Record) -> str:
    """Describe image format from recorded reader input, without guessing axes."""
    if case.get("image_kind"):
        return {"nifti": "NIfTI", "png": "PNG", "jpg": "JPEG", "jpeg": "JPEG"}.get(
            str(case["image_kind"]), str(case["image_kind"])
        )
    path = str(case.get("moving", "")).lower()
    for suffix, name in [
        (".nii.gz", "NIfTI"),
        (".nii", "NIfTI"),
        (".png", "PNG"),
        (".jpg", "JPEG"),
        (".jpeg", "JPEG"),
    ]:
        if path.endswith(suffix):
            return name
    if case.get("axis_interpretation"):
        return "Raster"
    return "Not recorded"


def group_statistics(cases: list[Record], key: Callable[[Record], str]) -> list[Record]:
    """Group counts and worst per-case errors without pooling incompatible images."""
    groups: dict[str, list[Record]] = defaultdict(list)
    for case in cases:
        groups[key(case)].append(case)
    rows = []
    for label, members in sorted(groups.items()):
        metrics = [case["metrics"] for case in members if case.get("metrics")]
        row = dict(
            label=label,
            total=len(members),
            counts=status_counts(members),
            status=overall_status(members),
            reasons=issue_counts(members, blocking_only=True),
            compared=len(metrics),
        )
        for metric in ("interior_max_abs", "interior_nrmse", "boundary_max_abs"):
            values = [item[metric] for item in metrics if metric in item]
            row[metric] = max(values) if values else None
        row["mismatches"] = sum(item.get("interior_mismatch_count", 0) for item in metrics)
        rows.append(row)
    return rows


def failed_families(cases: list[Record]) -> Record:
    """Count blocking failures/errors by the actual transform family."""
    return dict(
        Counter(family(case) for case in cases if case["status"] in {"fail", "error"}).most_common()
    )


def case_order(case: Record) -> tuple[int, str]:
    """Sort all human views consistently, showing actionable cases first."""
    return ({"error": 0, "fail": 1, "warning": 2, "pass": 3}.get(case["status"], 4), case["id"])


def format_number(value: Any) -> str:
    """Show missing metrics distinctly from genuine measured zeros."""
    return "—" if value is None else f"{value:,.6g}"


def software_statistics(reports: list[Record]) -> list[Record]:
    """Aggregate interfaces into one software summary with failing families/reasons."""
    grouped: dict[str, list[Record]] = defaultdict(list)
    for report in reports:
        grouped[report["backend"]].append(report)
    rows = []
    for backend, parts in sorted(grouped.items()):
        cases = [case for part in parts for case in part["cases"]]
        rows.append(
            dict(
                backend=backend,
                paths=[part["_report_path"] for part in parts],
                interfaces=[part["interface"] for part in parts],
                total=len(cases),
                status=overall_status(cases),
                counts=status_counts(cases),
                failed_families=failed_families(cases),
                failure_reasons=issue_counts(cases, blocking_only=True),
                boundary_cases=issue_counts(cases).get("boundary-difference", 0),
            )
        )
    return rows
