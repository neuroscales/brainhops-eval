"""Evaluate an immutable reference fixture with the installed brainhops."""

import importlib.metadata
import platform
import subprocess
import sys
import traceback
from pathlib import Path

import nibabel as nib
import numpy as np

from .files import digest, read_json, relative_file, verify, write_json
from .geometry import with_package_geometry
from .report import montage, write_report


def load_array(path):
    return np.load(path, allow_pickle=False) if Path(path).suffix == ".npy" else nib.load(path).get_fdata()


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


def evaluate(fixtures, output, brainhops_ref="installed", brainhops_sha="unknown", interface="python"):
    # Only this stage imports brainhops. Native fixtures are reusable across refs.
    import brainhops.io as bio
    from brainhops.backends import set_backend
    from brainhops.datamodel.images import SingleScaleImage
    from brainhops.datamodel.transformations import Affine

    set_backend("numpy")

    fixtures, output = Path(fixtures).resolve(), Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use an empty output directory to avoid stale reports")
    verify(fixtures, read_json(fixtures / "manifest.json"))
    output.mkdir(parents=True, exist_ok=True)
    manifest = read_json(fixtures / "cases.json")
    probes = read_json(fixtures / "geometry-probes.json")
    result = {"schema_version": 1, "brainhops_ref": brainhops_ref,
              "brainhops_sha": brainhops_sha,
              "brainhops_version": importlib.metadata.version("brainhops"),
              "fixture_manifest_sha256": digest(fixtures / "manifest.json"),
              "backend": manifest["backend"], "interface": interface, "python": platform.python_version(),
              "packages": {dist.metadata["Name"]: dist.version for dist in importlib.metadata.distributions()},
              "registration": read_json(fixtures / "registration.json"), "cases": []}
    for case in manifest["cases"]:
        record = {"id": case["id"], "status": "error"}
        case_output = output / case["id"]
        case_output.mkdir()
        try:
            src, ref, transform = [relative_file(fixtures, case[key]) for key in ("moving", "reference", "transform")]
            expected = load_array(relative_file(fixtures, case["expected"]))
            mask = np.load(relative_file(fixtures, case["mask"]), allow_pickle=False).astype(bool)
            if case["kind"] == "nifti":
                actual_path = case_output / "brainhops.nii.gz"
                if interface == "cli":
                    # Follow the documented push convention. A version whose CLI
                    # differs should fail visibly rather than be special-cased.
                    args = [sys.executable, "-m", "brainhops", "reslice", str(src),
                            "--reference", str(ref), "--transform", f"{transform}|inv",
                            "--output", str(actual_path), "--degree", str(case["degree"]), "--bound", "constant"]
                    process = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                    (case_output / "brainhops.log").write_text(repr(args) + "\n" + process.stdout)
                    process.check_returncode()
                else:
                    source = bio.images.load(src)
                    reference = bio.images.load(ref)
                    pull = bio.transformations.load(transform)
                    # State the geometry algebra explicitly, independently of
                    # the calling convention of Image.__call__ in a given ref.
                    moved = SingleScaleImage(
                        data=np.asarray(source.data, dtype=np.float32),
                        transformations=[pull.inverse() @ source.transformation],
                    )
                    resliced = moved.reslice(reference, degree=case["degree"], bound="constant")
                    bio.save(resliced, actual_path)
                image = nib.load(actual_path)
                reference = nib.load(ref)
                actual = image.get_fdata()
                reference_array = reference.get_fdata()
                if image.shape != reference.shape or not np.allclose(image.affine, reference.affine, atol=1e-4, rtol=1e-6):
                    raise ValueError("brainhops output geometry differs from the reference grid")
                record["output_dtype"] = str(image.get_data_dtype())
                if case["degree"] == 0:
                    allowed = np.append(np.unique(nib.load(src).get_fdata()), 0)
                    if not np.isin(actual, allowed).all():
                        raise ValueError("Nearest interpolation introduced a new label value")
            else:
                pull = bio.transformations.load(transform)
                arrays = []
                for label, path in [("moving", src), ("reference", ref)]:
                    if case["kind"] == "png":
                        loaded = bio.images.load(path)
                        data = np.asarray(loaded.data)
                        record[f"native_{label}_geometry"] = np.asarray(loaded.transformation.to(Affine).matrix).tolist()
                    else:
                        # NPY stores rows,columns by this fixture's explicit policy.
                        data = np.load(path, allow_pickle=False).T
                    arrays.append(with_package_geometry(data, probes[case["kind"]][label],
                                                        pull.output if label == "moving" else pull.input))
                moving, reference = arrays
                moved = SingleScaleImage(data=np.asarray(moving.data, dtype=np.float32),
                                         transformations=[pull.inverse() @ moving.transformation])
                actual = np.asarray(moved.reslice(reference, degree=1, bound="constant").data)
                reference_array = np.asarray(reference.data)
                np.save(case_output / "brainhops.npy", actual)
                record["geometry_policy"] = case["geometry_policy"]
            passed, metrics = compare(actual, expected, mask, atol=1e-5 if case["degree"] == 0 else 0.02)
            record.update(status="pass" if passed else "fail", metrics=metrics)
            montage(case_output / "comparison.png", reference_array, expected, actual)
            record["preview"] = f"{case['id']}/comparison.png"
        except Exception:
            record["error"] = traceback.format_exc()
        result["cases"].append(record)
        print(f"{record['status']:5} {record['id']}", flush=True)
    result["passed"] = bool(result["cases"]) and all(case["status"] == "pass" for case in result["cases"])
    write_json(output / "results.json", result)
    write_report(output, result)
    return result["passed"]

