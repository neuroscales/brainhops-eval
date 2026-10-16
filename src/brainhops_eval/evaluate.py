"""Orchestrate immutable-fixture evaluation using the selected brainhops version."""

from __future__ import annotations

import importlib.metadata
import os
import platform
import traceback
import warnings
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np

from .boundaries import policy_for
from .comparison import assess, compare, conclude, reference_in_output_dtype
from .files import digest, read_json, relative_file, verify, write_json
from .report import montage, write_report
from .resampling import (
    CasePaths,
    execute,
    expected_on_reference_grid,
    load_array,
    load_transform,
    transform_source,
)
from .types import PathLike, Record

# Retain the small public helpers imported by existing users and tests.
__all__ = [
    "evaluate",
    "compare",
    "reference_in_output_dtype",
    "load_array",
    "expected_on_reference_grid",
    "load_transform",
    "transform_source",
]


def _provenance(
    fixtures: Path, manifest: Record, brainhops_ref: str, brainhops_sha: str, interface: str
) -> Record:
    """Record immutable versions, fixture identity, registration, and reader probes."""
    result = dict(
        schema_version=2,
        brainhops_ref=brainhops_ref,
        brainhops_sha=brainhops_sha,
        brainhops_version=importlib.metadata.version("brainhops"),
        evaluator_version=importlib.metadata.version("brainhops-eval"),
        evaluator_sha=os.environ.get("BRAINHOPS_EVAL_SHA", "unknown"),
        fixture_manifest_sha256=digest(fixtures / "manifest.json"),
        backend=manifest["backend"],
        interface=interface,
        python=platform.python_version(),
        source=read_json(fixtures / "inputs/inputs.json")["source"],
        transform_convention=manifest["transform_convention"],
        geometry_probes=read_json(fixtures / "geometry-probes.json"),
        packages={
            dist.metadata["Name"]: dist.version for dist in importlib.metadata.distributions()
        },
        registration=read_json(fixtures / "registration.json"),
        cases=[],
    )
    for filename, key in [
        ("coverage.json", "transform_coverage"),
        ("boundary-probes.json", "boundary_probes"),
    ]:
        if (fixtures / filename).exists():
            result[key] = read_json(fixtures / filename)
    return result


def _expectation(paths: CasePaths, case: Record, record: Record) -> tuple[np.ndarray, np.ndarray]:
    """Read native reference values and the independently generated interior mask."""
    record["stage"] = "read native reference"
    expected = load_array(paths.expected)
    if case["kind"] == "nifti":
        expected, record["native_output_axis_reordering"] = expected_on_reference_grid(
            paths.expected, paths.reference
        )
    record["reference_output_dtype"] = str(
        expected.dtype
        if paths.expected.suffix == ".npy"
        else nib.load(paths.expected).get_data_dtype()
    )
    mask = np.load(paths.mask, allow_pickle=False).astype(bool)
    return expected, mask


def _initial_record(case: Record, backend: str, interface: str) -> Record:
    """Describe the exact input transform and requested application settings."""
    return dict(
        id=case["id"],
        status="error",
        stage="prepare case",
        moving=case["moving"],
        reference_image=case["reference"],
        transform=case["transform"],
        transform_hint=case.get("transform_hint"),
        transform_images=case.get("transform_images", {}),
        transform_options=case.get("transform_options", {}),
        transform_family=case.get("transform_family", "affine"),
        transform_representation=case.get("transform_representation"),
        degree=case["degree"],
        boundary_policy=policy_for(backend, case),
        interface=interface if case["kind"] == "nifti" else "python",
    )


def _case(bio: Any, fixtures: Path, output: Path, case: Record, context: Record) -> Record:
    """Run one case, retaining exceptions and a concise reason in the report."""
    record = _initial_record(case, context["backend"], context["interface"])
    directory = relative_file(output, case["id"])
    directory.mkdir()
    try:
        paths = CasePaths.resolve(fixtures, directory, case)
        expected, mask = _expectation(paths, case, record)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            arrays = execute(bio, fixtures, paths, case, context["geometry_probes"], record)
        record["warnings"] = [str(warning.message) for warning in caught]
        record["stage"] = "compare output"
        assessment, panel_expected = assess(arrays.actual, expected, mask, case["degree"])
        record.update(assessment)
        conclude(record)
        record["stage"] = "render montage"
        montage(
            directory / "comparison.png",
            arrays.reference,
            panel_expected,
            arrays.actual,
            window=case.get("display_window"),
        )
        record.update(
            display_window=case.get("display_window"),
            preview=f"{case['id']}/comparison.png",
            stage="complete",
        )
    except Exception as error:
        record.update(
            status="error",
            error=traceback.format_exc(),
            error_type=type(error).__name__,
            error_summary=str(error),
            summary=f"{record['stage'].capitalize()} failed: {type(error).__name__}: {(str(error).strip().splitlines() or [type(error).__name__])[-1]}",
        )
    return record


def _save_report(output: Path, result: Record) -> None:
    """Write portable JSON, coverage, registration and HTML even after case failures."""
    result["passed"] = bool(result["cases"]) and all(
        case["status"] in ("pass", "warning") for case in result["cases"]
    )
    for filename, key in [
        ("registration.json", "registration"),
        ("coverage.json", "transform_coverage"),
        ("boundary-probes.json", "boundary_probes"),
    ]:
        if key in result:
            write_json(output / filename, result[key])
    write_json(output / "results.json", result)
    write_report(output, result)


def evaluate(
    fixtures: PathLike,
    output: PathLike,
    brainhops_ref: str = "installed",
    brainhops_sha: str = "unknown",
    interface: str = "python",
) -> bool:
    """Evaluate every native case and write a report; return interior acceptance.

    The selected brainhops is imported only here. Source/reference images are
    used directly from its readers; no replacement objects or geometry fixes
    are applied. Boundary-only discrepancies warn, and reader/interior failures
    fail the run. An empty output directory prevents stale results.
    """
    import brainhops.io as bio
    from brainhops.backends import set_backend

    set_backend("numpy")
    fixtures, output = Path(fixtures).resolve(), Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use an empty output directory to avoid stale reports")
    verify(fixtures, read_json(fixtures / "manifest.json"))
    output.mkdir(parents=True, exist_ok=True)
    manifest = read_json(fixtures / "cases.json")
    result = _provenance(fixtures, manifest, brainhops_ref, brainhops_sha, interface)
    for case in manifest["cases"]:
        record = _case(bio, fixtures, output, case, result)
        result["cases"].append(record)
        print(f"{record['status']:7} {record['id']}: {record['summary']}", flush=True)
    _save_report(output, result)
    return result["passed"]
