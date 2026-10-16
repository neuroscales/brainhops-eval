"""Compare native edge probes using the selected upstream brainhops public API."""

from __future__ import annotations

import warnings
from copy import deepcopy
from typing import Any

import numpy as np

from .boundaries import policy_for, reslice_options
from .files import relative_file
from .types import PathLike, Record


def _sample(bio: Any, fixtures: PathLike, probe: Record, sample: Record, context: Record) -> Record:
    """Reslice original reader objects without reproducing boundary arithmetic."""
    policy = policy_for(
        context["backend"],
        dict(degree=sample["degree"]),
        supports_clip=context["reslice_capabilities"]["clip"],
    )
    options = dict(degree=sample["degree"], **reslice_options(policy))
    source = bio.images.load(
        relative_file(fixtures, probe.get("source", "boundary-probe/ramp.nii.gz"))
    )
    reference = bio.images.load(
        relative_file(fixtures, probe.get("reference", "boundary-probe/reference.nii.gz"))
    )
    # The native probe applies an identity map in world space. Reader geometry
    # therefore supplies the whole map; no new image or transform is constructed.
    output = source.reslice(reference, **options)
    actual = np.asarray(output.data)[:, 0, 0]
    native = np.asarray(sample["native_values"])
    if actual.shape != native.shape:
        raise ValueError("brainhops boundary probe does not match the native sampling grid")
    if not np.isfinite(actual).all():
        raise ValueError("Non-finite brainhops boundary probe samples")
    difference = actual.astype(float) - native
    return dict(
        status="measured",
        options=options,
        policy=policy,
        values=actual.tolist(),
        max_abs=float(np.max(np.abs(difference))),
        rmse=float(np.sqrt(np.mean(difference**2))),
        mismatch_count=int(np.count_nonzero(np.abs(difference) > 1e-4)),
    )


def evaluate_boundary_probes(bio: Any, fixtures: PathLike, context: Record) -> Record:
    """Retain native evidence and add actual upstream reslice samples per degree.

    Old fixture bundles without probes remain supported. Probe errors are
    explicit diagnostics, independent of the anatomical acceptance decisions.
    """
    probe = deepcopy(context.get("boundary_probes", {}))
    for sample in probe.get("interpolation", []):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                measurement = _sample(bio, fixtures, probe, sample, context)
            except Exception as error:
                measurement = dict(
                    status="error", error_type=type(error).__name__, error=str(error)
                )
        measurement["warnings"] = [str(item.message) for item in caught]
        sample["brainhops"] = measurement
    return probe
