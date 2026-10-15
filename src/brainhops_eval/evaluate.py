"""Evaluate an immutable reference fixture with the installed brainhops."""

import importlib.metadata
import os
import platform
import subprocess
import sys
import traceback
import warnings
from urllib.parse import quote
from pathlib import Path

import nibabel as nib
import numpy as np

from .files import digest, read_json, relative_file, verify, write_json
from .axes import raster_axis_check
from .report import montage, write_report


def load_array(path):
    return np.load(path, allow_pickle=False) if Path(path).suffix == ".npy" else nib.load(path).get_fdata()


def expected_on_reference_grid(path, reference):
    """Undo lossless native axis storage changes; never interpolate expected data."""
    image, ref = nib.load(path), nib.load(reference)
    orientation = nib.orientations.ornt_transform(
        nib.orientations.io_orientation(image.affine), nib.orientations.io_orientation(ref.affine))
    aligned = image.as_reoriented(orientation)
    if aligned.shape != ref.shape or not np.allclose(aligned.affine, ref.affine, atol=1e-4, rtol=1e-6):
        raise ValueError("Native output is not on the reference grid, even after lossless axis reordering")
    return aligned.get_fdata(), orientation.tolist()


def reference_in_output_dtype(expected, dtype):
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


def compare(actual, expected, mask, atol=0.02, nrmse_limit=2e-5):
    if actual.shape != expected.shape or mask.shape != expected.shape:
        raise ValueError("Output, expectation, and mask shapes must match")
    if not np.isfinite(actual).all() or not np.isfinite(expected).all():
        raise ValueError("Non-finite image values")
    fraction = float(mask.mean())
    if fraction < 0.05:
        raise ValueError(f"Insufficient interior overlap: {fraction:.2%}")
    error = np.abs(actual.astype(float) - expected)
    span = max(float(np.ptp(expected)), 1)
    maximum = float(error[mask].max())
    nrmse = float(np.sqrt(np.mean(error[mask] ** 2)) / span)
    metrics = {"interior_fraction": fraction, "interior_max_abs": maximum,
               "interior_nrmse": nrmse,
               "boundary_max_abs": float(error[~mask].max()) if (~mask).any() else 0,
               "all_voxels_rmse": float(np.sqrt(np.mean(error ** 2))),
               "atol": atol, "nrmse_limit": nrmse_limit}
    return maximum <= atol and nrmse <= nrmse_limit, metrics


def transform_source(fixtures, case):
    """A portable CLI source spec, including optional original image geometries."""
    spec = quote(str(relative_file(fixtures, case["transform"])), safe="/:._-")
    if case.get("transform_hint"):
        spec += "|" + case["transform_hint"]
    for name, path in case.get("transform_images", {}).items():
        spec += f"|{name}:[{quote(str(relative_file(fixtures, path)), safe='/:._-')}]"
    return spec


def load_transform(bio, fixtures, case):
    options = {name: bio.images.load(relative_file(fixtures, path))
               for name, path in case.get("transform_images", {}).items()}
    if case.get("transform_hint"):
        options["hint"] = case["transform_hint"]
    return bio.load(relative_file(fixtures, case["transform"]), **options)


def evaluate(fixtures, output, brainhops_ref="installed", brainhops_sha="unknown", interface="python"):
    # Only this stage imports brainhops. Native fixtures are reusable across refs.
    import brainhops.io as bio
    from brainhops.backends import set_backend

    set_backend("numpy")

    fixtures, output = Path(fixtures).resolve(), Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use an empty output directory to avoid stale reports")
    verify(fixtures, read_json(fixtures / "manifest.json"))
    output.mkdir(parents=True, exist_ok=True)
    manifest = read_json(fixtures / "cases.json")
    probes = read_json(fixtures / "geometry-probes.json")
    result = {"schema_version": 1, "brainhops_ref": brainhops_ref,
              "evaluator_version": importlib.metadata.version("brainhops-eval"),
              "evaluator_sha": os.environ.get("BRAINHOPS_EVAL_SHA", "unknown"),
              "brainhops_sha": brainhops_sha,
              "brainhops_version": importlib.metadata.version("brainhops"),
              "fixture_manifest_sha256": digest(fixtures / "manifest.json"),
              "backend": manifest["backend"], "interface": interface, "python": platform.python_version(),
              "source": read_json(fixtures / "inputs/inputs.json")["source"],
              "transform_convention": manifest["transform_convention"],
              "geometry_probes": probes,
              "packages": {dist.metadata["Name"]: dist.version for dist in importlib.metadata.distributions()},
              "registration": read_json(fixtures / "registration.json"), "cases": []}
    for case in manifest["cases"]:
        record = {"id": case["id"], "status": "error", "transform": case["transform"],
                  "transform_hint": case.get("transform_hint"),
                  "transform_images": case.get("transform_images", {}),
                  "interface": interface if case["kind"] == "nifti" else "python"}
        case_output = output / case["id"]
        case_output.mkdir()
        try:
            src, ref, transform = [relative_file(fixtures, case[key]) for key in ("moving", "reference", "transform")]
            expected_path = relative_file(fixtures, case["expected"])
            if case["kind"] == "nifti":
                expected, record["native_output_axis_reordering"] = expected_on_reference_grid(expected_path, ref)
            else:
                expected = load_array(expected_path)
            record["reference_output_dtype"] = str(expected.dtype if expected_path.suffix == ".npy"
                                                   else nib.load(expected_path).get_data_dtype())
            mask = np.load(relative_file(fixtures, case["mask"]), allow_pickle=False).astype(bool)
            if case["kind"] == "nifti":
                actual_path = case_output / "brainhops.nii.gz"
                if interface == "cli":
                    # Follow the documented push convention. A version whose CLI
                    # differs should fail visibly rather than be special-cased.
                    args = [sys.executable, "-m", "brainhops", "reslice", str(src),
                            "--reference", str(ref), "--transform", transform_source(fixtures, case) + "|inv",
                            "--output", str(actual_path), "--degree", str(case["degree"]), "--bound", "constant"]
                    process = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                    (case_output / "brainhops.log").write_text(repr(args) + "\n" + process.stdout)
                    process.check_returncode()
                else:
                    source = bio.images.load(src)
                    reference = bio.images.load(ref)
                    pull = load_transform(bio, fixtures, case)
                    with warnings.catch_warnings(record=True) as caught:
                        warnings.simplefilter("always")
                        resliced = source(pull).reslice(reference, degree=case["degree"], bound="constant")
                    record["warnings"] = [str(warning.message) for warning in caught]
                    record["in_memory_output_dtype"] = str(resliced.data.dtype)
                    bio.save(resliced, actual_path)
                image = nib.load(actual_path)
                reference = nib.load(ref)
                source_storage = nib.load(src)
                record["input"] = {"shape": list(source_storage.shape),
                                   "dtype": str(source_storage.get_data_dtype()),
                                   "affine_ras": source_storage.affine.tolist(),
                                   "axcodes": list(nib.aff2axcodes(source_storage.affine))}
                record["reference"] = {"shape": list(reference.shape),
                                       "affine_ras": reference.affine.tolist()}
                # Preserve the decoded output dtype, including NIfTI scaling.
                actual = np.asanyarray(image.dataobj)
                reference_array = reference.get_fdata()
                if image.shape != reference.shape or not np.allclose(image.affine, reference.affine, atol=1e-4, rtol=1e-6):
                    raise ValueError("brainhops output geometry differs from the reference grid")
                record["output_dtype"] = str(image.get_data_dtype())
                if case["degree"] == 0:
                    allowed = np.append(np.unique(nib.load(src).get_fdata()), 0)
                    if not np.isin(actual, allowed).all():
                        raise ValueError("Nearest interpolation introduced a new label value")
            else:
                pull = load_transform(bio, fixtures, case)
                source = bio.images.load(src)
                reference = bio.images.load(ref)
                record["axis_interpretation"] = {
                    "moving": raster_axis_check(source, src, probes[case["kind"]]["moving"]),
                    "reference": raster_axis_check(reference, ref, probes[case["kind"]]["reference"]),
                }
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    actual = np.asarray(source(pull).reslice(reference, degree=1, bound="constant").data)
                record["warnings"] = [str(warning.message) for warning in caught]
                reference_array = np.asarray(reference.data)
                np.save(case_output / "brainhops.npy", actual)
                record["geometry_policy"] = "unmodified io.images.load defaults"
            _, raw_metrics = compare(actual, expected, mask, atol=1e-5 if case["degree"] == 0 else 0.02)
            comparison_expected = reference_in_output_dtype(expected, actual.dtype)
            integer_output = actual.dtype.kind in "biu"
            passed, metrics = compare(actual, comparison_expected, mask,
                                      atol=0 if integer_output else (1e-5 if case["degree"] == 0 else 0.02),
                                      nrmse_limit=0 if integer_output else 2e-5)
            if integer_output:
                mismatches = int(np.count_nonzero(actual[mask] != comparison_expected[mask]))
                metrics["interior_mismatch_count"] = mismatches
                passed = mismatches == 0
            record["comparison_dtype"] = str(actual.dtype)
            record["comparison_policy"] = "reference converted to decoded brainhops output dtype; integer equality is exact"
            record["raw_reference_metrics"] = raw_metrics
            passed = passed and all(check["passed"] for check in record.get("axis_interpretation", {}).values())
            record.update(status="pass" if passed else "fail", metrics=metrics)
            montage(case_output / "comparison.png", reference_array, comparison_expected, actual,
                    window=case.get("display_window"))
            record["display_window"] = case.get("display_window")
            record["preview"] = f"{case['id']}/comparison.png"
        except Exception:
            record["error"] = traceback.format_exc()
        result["cases"].append(record)
        print(f"{record['status']:5} {record['id']}", flush=True)
    result["passed"] = bool(result["cases"]) and all(case["status"] == "pass" for case in result["cases"])
    write_json(output / "registration.json", result["registration"])
    write_json(output / "results.json", result)
    write_report(output, result)
    return result["passed"]

