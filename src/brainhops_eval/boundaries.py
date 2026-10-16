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


def policy_for(backend: str, case: Record) -> Record:
    """Return the public reslice option and the native convention being tested."""
    native_rule = _NATIVE_RULES.get(backend, "Native image boundary rule is not documented.")
    if backend == "fsl" and case.get("transform_hint") == "fnirt":
        native_rule = "applywarp with default padding; the FLIRT affine edge probe does not establish nonlinear-field validity."
    return dict(
        brainhops_bound=case.get("brainhops_bound", "constant"),
        native_rule=native_rule,
        scope="Image interpolation; transform-field extension is controlled by its reader.",
        selection="Declared recipe policy, not selected per case to minimise error.",
        note="brainhops constant means grid-zero padding. Half-voxel clipping/clamping may have no exact public equivalent.",
    )
