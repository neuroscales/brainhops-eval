"""Separate direct spline evaluation from FSL's rasterized application path."""

from copy import deepcopy
from pathlib import Path

from brainhops_eval.files import inventory, read_json, relative_file, write_json


def append_rebased_cases(output: Path) -> None:
    """Add comparisons that load the exact dense warp passed to applywarp.

    The original coefficient cases remain unchanged in acceptance policy.
    They compare direct spline evaluation with FSL's additional rasterization
    and rebasing steps. The new cases isolate application of the same stored
    map, using the variant images as the dense field's coordinate frames.
    Expected images and masks are shared immutable native outputs.
    """
    manifest = read_json(output / "cases.json")
    coverage = read_json(output / "coverage.json")
    added = []
    for case in manifest["cases"]:
        if not case.get("transform_family", "").startswith("bspline-order"):
            continue
        native_warp = str(Path(case["expected"]).with_name("expected-rebased.nii.gz"))
        if not relative_file(output, native_warp).is_file():
            raise FileNotFoundError(f"Missing native applywarp input: {native_warp}")
        case["native_application"] = "convertwarp rasterization and rebasing, then applywarp"
        case["brainhops_application"] = "Evaluate the original coefficient spline directly"
        case["comparison_note"] = (
            "These pipelines differ by a native dense rasterization step. "
            "The same-warp companion case isolates application agreement. "
            "Acceptance thresholds are unchanged."
        )
        exact = deepcopy(case)
        exact.update(
            id="same-warp-" + case["id"],
            transform=native_warp,
            transform_family=case["transform_family"] + "-native-rebased-dense",
            transform_representation="FNIRT relative dense field passed to applywarp",
            transform_origin="native-conversion",
            transform_options={"deformation_type": "relative"},
            transform_images={"moving": case["moving"], "reference": case["reference"]},
            native_application="applywarp on the stored rebased dense warp",
            brainhops_application="Load and apply the same stored rebased dense warp",
            comparison_note="Both samplers apply the same native-converted transformation file.",
        )
        added.append(exact)
        coverage["tested"].append(
            dict(
                id=exact["id"],
                family=exact["transform_family"],
                representation=exact["transform_representation"],
                origin=exact["transform_origin"],
                transform=native_warp,
                cases=[exact["id"]],
            )
        )
    manifest["cases"].extend(added)
    write_json(output / "cases.json", manifest)
    write_json(output / "coverage.json", coverage)
    write_json(output / "manifest.json", {"schema_version": 1, "files": inventory(output)})
