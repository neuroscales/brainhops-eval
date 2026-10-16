"""Native fractional-voxel image-edge probes, independent of brainhops.

Per-software recipes provide their actual writer/application callbacks. The
probe uses a nonzero float ramp so zero padding, whole-sample clipping, and
half-voxel clamping can be distinguished without integer quantisation.
"""
from pathlib import Path
from typing import Callable

import nibabel as nib
import numpy as np
from scipy.ndimage import map_coordinates

from brainhops_eval.files import inventory, read_json, write_json
from software._shared.nonlinear import aligned


def _predictions(values: np.ndarray, coords: np.ndarray, degree: int) -> dict[str, np.ndarray]:
    """Calculate named edge models independently of every native application."""
    models = {mode: map_coordinates(values, coords, order=degree, mode=mode, cval=0,
                                     prefilter=False)
              for mode in ('grid-constant', 'constant', 'nearest', 'reflect', 'mirror')}
    shape = np.array(values.shape)[:, None]
    inside = np.all((coords >= -.5) & (coords < shape - .5), axis=0)
    models['half-voxel-clamp'] = np.where(inside, models['nearest'], 0)
    models['half-voxel-mirror'] = np.where(inside, models['mirror'], 0)
    strict = np.all((coords > -.5) & (coords < shape - .5), axis=0)
    models['strict-half-voxel-clamp'] = np.where(strict, models['nearest'], 0)
    closed_half = np.all((coords >= -.5) & (coords <= shape - .5), axis=0)
    closed_centres = np.all((coords >= 0) & (coords <= shape - 1), axis=0)
    models['nearest-clip-half-closed'] = np.where(closed_half, models['nearest'], 0)
    models['mirror-clip-half-closed'] = np.where(closed_half, models['mirror'], 0)
    models['nearest-clip-centres-closed'] = np.where(closed_centres, models['nearest'], 0)
    return models


def probe(output: Path, backend: str, write_transform: Callable, apply_image: Callable,
          extension: str = 'txt') -> dict:
    """Apply a native identity map across both source edges at fractional voxels.

    The callbacks have the same signatures as affine recipes. Results include
    every sample and per-model residuals; a fit is descriptive, not a licence
    to change an individual anatomical comparison or alter a loaded image.
    """
    output = Path(output)
    folder = output / 'boundary-probe'
    folder.mkdir()
    indices = np.indices((9, 10, 11), dtype=float)
    values = (10 + 2 * indices[0] + 3 * indices[1] + 5 * indices[2]).astype(np.float32)
    source = folder / 'ramp.nii.gz'
    reference = folder / 'reference.nii.gz'
    nib.save(nib.Nifti1Image(values, np.eye(4)), source)
    affine = np.diag([.125, 1., 1., 1.])
    affine[:3, 3] = [-1.25, 2.25, 3.25]
    nib.save(nib.Nifti1Image(np.zeros((85, 2, 2), np.float32), affine), reference)
    x = -1.25 + .125 * np.arange(85)
    coords = np.stack([x, np.full_like(x, 2.25), np.full_like(x, 3.25)])
    results = []
    for degree in (0, 1):
        degree_folder = folder / f'degree{degree}'
        degree_folder.mkdir()
        path = degree_folder / 'native.nii.gz'
        transform = degree_folder / ('identity.' + extension)
        write_transform(transform, np.eye(4), source, reference)
        apply_image(source, reference, transform, degree, path, output / 'commands.log')
        native = aligned(path, reference)[:, 0, 0]
        models = _predictions(values, coords, degree)
        # FLIRT's estimated background is a separate observed native value.
        # This diagnostic fits its clipping rule, not an anatomical test case.
        center_inside = np.all((coords >= 0) & (coords <= np.array(values.shape)[:, None] - 1), axis=0)
        models['center-clipped-background'] = np.where(center_inside, models['nearest'], native[0])
        errors = {name: dict(max_abs=float(np.max(abs(native - expected))),
                              rmse=float(np.sqrt(np.mean((native - expected) ** 2))))
                  for name, expected in models.items()}
        results.append(dict(degree=degree, native_values=native.tolist(),
                            measured_far_background=float(native[0]),
                            model_errors=errors,
                            model_values={name: values.tolist() for name, values in models.items()},
                            matching_models=[name for name, error in errors.items() if error['max_abs'] < 1e-4]))
    result = dict(schema_version=1, backend=backend, sample_x_voxels=x.tolist(),
                  source_shape=list(values.shape), source_edge_centers=[0, 8], requested_background=0 if backend != 'fsl' else 'FLIRT native default',
                  probe_scope='Affine image application; nonlinear transform-field boundaries are separate.',
                  native_provenance=read_json(output / 'registration.json'),
                  public_brainhops_modes={'constant': 'grid-constant', 'nearest': 'nearest',
                                           'reflect': 'reflect', 'mirror': 'mirror'},
                  note='Only named public modes are selectable. Clipped models are diagnostic; center-clipped-background uses the measured far-background sample.',
                  interpolation=results)
    write_json(output / 'boundary-probes.json', result)
    write_json(output / 'manifest.json', dict(schema_version=1, files=inventory(output)))
    return result
