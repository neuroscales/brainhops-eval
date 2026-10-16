"""Declared image boundary policies, separate from transformation-field boundaries.

Policies are fixed by software conventions, never fitted to individual anatomy
or chosen after observing a failed comparison. Native edge probes provide the
empirical evidence and may show that no public brainhops option matches exactly.
"""

from .types import Record

_NATIVE_RULES = {
    "simpleitk": "ITK image interpolation: clamp within the half-voxel image extent; zero outside.",
    "ants": "ITK image interpolation: clamp within the half-voxel image extent; zero outside.",
    "elastix": "transformix: half-voxel image extent with zero outside; linear B-spline interpolation mirrors at the edge.",
    "niftyreg": "reg_resample with -pad 0: zero contributions outside the voxel grid.",
    "fsl": "FLIRT defaults to estimated background outside the voxel-center FOV; applywarp is a distinct sampler.",
    "mrtrix": "mrtransform clamps inside the strict half-voxel extent and returns zero outside; transform-field validity is separate.",
}


def policy_for(backend: str, case: Record, *, supports_clip: bool = False) -> Record:
    """Select one fixed software/interpolator policy, independent of case errors.

    Old brainhops versions retain a declared fallback when they lack `clip`.
    FLIRT retains grid-zero: a ramp-only optimum (mirror) worsens
    anatomical edges and does not reproduce its estimated background.
    """
    native_rule = _NATIVE_RULES.get(backend, "Native image boundary rule is not documented.")
    bound, clip = "constant", None
    note = "Grid-zero interpolation matches the NiftyReg linear edge probe."
    if backend in {"simpleitk", "ants", "elastix", "mrtrix"}:
        note = (
            "Nearest-neighbour grid-zero sampling retains the closest measured endpoint convention."
        )
        if case.get("degree", 1) > 0:
            bound = "mirror" if backend == "elastix" else "nearest"
            clip = 0.5
            note = "Clamped/mirrored interpolation inside the half-voxel extent; closed clip endpoints can differ from native open/half-open endpoints."
    if backend == "fsl":
        note = "Retain grid-zero: mirror improves the synthetic ramp but worsens anatomical edges. FLIRT estimated exterior background remains unmatched."
        if case.get("transform_hint") == "fnirt":
            bound = "constant"
            native_rule = "applywarp with default padding; the FLIRT affine edge probe does not establish nonlinear-field validity."
            note = "Retain grid-zero for applywarp; no FLIRT-derived clipping or background rule is assumed."
    requested = dict(
        bound=case.get("brainhops_bound", bound), clip=case.get("brainhops_clip", clip)
    )
    actual = dict(requested)
    fallback = ""
    if actual["clip"] is not None and not supports_clip:
        actual = dict(bound="constant", clip=None)
        fallback = "Selected brainhops has no public clip argument; use the legacy grid-zero approximation."
    return dict(
        brainhops_bound=actual["bound"],
        brainhops_clip=actual["clip"],
        requested=requested,
        capability_fallback=fallback,
        native_rule=native_rule,
        scope="Image interpolation; transform-field extension is controlled by its reader.",
        selection="Fixed by software/interpolator and independent native probes; never fitted to individual anatomical cases.",
        note=note,
    )


def reslice_options(policy: Record) -> Record:
    """Build native reslice kwargs without passing new options to old versions."""
    options = dict(bound=policy["brainhops_bound"])
    if policy.get("brainhops_clip") is not None:
        options["clip"] = policy["brainhops_clip"]
    return options
