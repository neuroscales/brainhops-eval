"""Reproduce native affine loss using loaded files, without native executables.

Run: python scripts/diagnose_affine_readers.py --output work/affine-diagnostic
Returns nonzero if conversion or direct loaded-image reslicing loses the map.
"""

import argparse
import importlib.metadata
from pathlib import Path

import nibabel as nib
import numpy as np

from brainhops_eval.files import write_json


def diagnose(output):
    import brainhops.io as io
    from brainhops.backends import set_backend
    from brainhops.datamodel.transformations import Affine

    set_backend("numpy")
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use an empty output directory")
    output.mkdir(parents=True, exist_ok=True)
    indices = np.indices((7, 8, 9), dtype=np.float32)
    values = 100 * indices[0] + 10 * indices[1] + indices[2]
    geometry = np.diag([1.25, 1.5, 2., 1.])
    # A one-voxel x pull should increase this ramp by exactly 100.
    pull = np.eye(4)
    pull[0, 3] = 1.25
    for name in ("moving", "reference"):
        image = nib.Nifti1Image(values, geometry)
        image.set_sform(geometry, code=1)
        image.set_qform(geometry, code=1)
        nib.save(image, output / f"{name}.nii.gz")
    results = {"brainhops_version": importlib.metadata.version("brainhops"), "cases": []}
    for hint in ("niftyreg.aladin", "mrtrix.linear"):
        path = output / (hint + ".txt")
        np.savetxt(path, pull, fmt="%.15g")
        source = io.images.load(output / "moving.nii.gz")
        reference = io.images.load(output / "reference.nii.gz")
        transform = io.load(path, hint=hint)
        # This is the production API under investigation. No reconstructed
        # images or substituted transformations are used in this call.
        actual = np.asarray(source(transform).reslice(reference, degree=1, bound="constant").data)
        converted_matrix = transform.to(Affine).matrix
        expected = values[1:, 1:-1, 1:-1]
        tested = actual[:-1, 1:-1, 1:-1]
        stored = getattr(transform, "_data", None)
        record = {
            "hint": hint, "reader": type(transform).__name__,
            "loaded_matrix": np.asarray(transform.matrix).tolist(),
            "inherited_stored_data_is_none": stored is None,
            "generic_affine_matrix": None if converted_matrix is None else np.asarray(converted_matrix).tolist(),
            "conversion_preserves_map": converted_matrix is not None and bool(np.allclose(converted_matrix, pull[:3])),
            "interior_max_abs": float(np.max(np.abs(tested - expected))),
            "matches_untransformed_interior": bool(np.array_equal(tested, values[:-1, 1:-1, 1:-1])),
            "input_dtype": str(source.data.dtype), "output_dtype": str(actual.dtype),
        }
        record["passed"] = record["conversion_preserves_map"] and record["interior_max_abs"] < 1e-5
        results["cases"].append(record)
    results["passed"] = all(record["passed"] for record in results["cases"])
    write_json(output / "diagnostic.json", results)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    result = diagnose(**vars(parser.parse_args()))
    for case in result["cases"]:
        print(case["hint"], "pass" if case["passed"] else "fail",
              f"interior max error={case['interior_max_abs']}",
              f"conversion preserves map={case['conversion_preserves_map']}")
    raise SystemExit(0 if result["passed"] else 1)
