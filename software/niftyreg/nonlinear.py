"""All NREG_TRANS_TYPE field/grid encodings, plus registration and composition."""

from pathlib import Path
import subprocess

import nibabel as nib
import numpy as np

from software._shared.affine import command
from software._shared.nonlinear import append_cases, smooth_displacement, world_grid


def write_field(path, values, affine, kind, steps=0):
    image = nib.Nifti1Image(values[..., None, :].astype(np.float32), affine)
    image.header.set_intent('vector', (), name='NREG_TRANS')
    image.header['intent_p1'] = kind
    image.header['intent_p2'] = steps
    image.header.set_xyzt_units('mm')
    image.set_sform(affine, code=1)
    image.set_qform(affine, code=1)
    nib.save(image, path)


def apply_image(entry, source, reference, degree, output, log):
    command(['reg_resample', '-ref', reference, '-flo', source, '-trans', entry['transform'],
             '-res', output, '-inter', str(degree), '-pad', '0', '-omp', '1'], log)


def append(output):
    output = Path(output)
    folder = output / 'transforms/niftyreg-nonlinear'
    folder.mkdir()
    fixed, moving = output / 'inputs/fixed.nii.gz', output / 'inputs/moving.nii.gz'
    log = output / 'commands.log'
    ref = nib.load(fixed)
    points = world_grid(ref)
    entries, unavailable = [], []
    for name, kind, hint, sparse in [
        ('deformation', 0, 'niftyreg.deformation', False),
        ('displacement', 1, 'niftyreg.displacement', False),
        ('cubic-control-grid', 2, 'niftyreg.cpp', True),
        ('linear-control-grid', 6, 'niftyreg.cpp', True),
        ('dense-velocity-positions', 3, 'niftyreg.velocity', False),
        ('dense-velocity-displacements', 4, 'niftyreg.velocity', False),
        ('spline-velocity', 5, 'niftyreg.velocity', True),
    ]:
        affine = ref.affine
        grid = points
        if sparse:
            affine = np.diag([10., 10., 10., 1.])
            affine[:3, 3] = [-60, -60, -60]
            grid = world_grid(nib.Nifti1Image(np.zeros((13, 13, 13)), affine))
        displacement = smooth_displacement(grid)
        values = displacement if kind in (1, 4) else grid + displacement
        path = folder / (name + '.nii.gz')
        write_field(path, values, affine, kind, 4 if kind in (3, 4, 5) else 0)
        entries.append(dict(id='nonlinear-known-' + name, family=name,
                            representation=f'NREG_TRANS_TYPE={kind}', transform=path,
                            transform_hint=hint, origin='known-native', domain='inputs/fixed.nii.gz'))
        # Conversion is native; applying both files tests the interpretation of
        # coefficients/velocities separately from the dense representation.
        dense = folder / (name + '-integrated.nii.gz')
        try:
            command(['reg_transform', '-ref', fixed, '-def', path, dense, '-omp', '1'], log)
        except subprocess.CalledProcessError as error:
            if kind != 4 or 'not a velocity field' not in (error.output or ''):
                raise
            unavailable.append({'family': name + '-to-deformation',
                                'reason': 'NiftyReg 2.1.2 reg_transform aborts on DISP_VEL_FIELD; original native reg_resample application is tested',
                                'command_log': 'commands.log'})
            continue
        entries.append(dict(id='nonlinear-converted-' + name, family=name + '-to-deformation',
                            representation='NREG_TRANS_TYPE=0', transform=dense,
                            transform_hint='niftyreg.deformation', origin='native-conversion', domain='inputs/fixed.nii.gz'))
        if kind in (0, 1):
            actual = nib.load(dense).get_fdata().reshape((*ref.shape, 3))
            expected = points + smooth_displacement(points)
            if np.max(abs(actual - expected)) > .002:
                raise ValueError('NiftyReg known dense map changed physical points')
    registered = folder / 'registered-cpp.nii.gz'
    command(['reg_f3d', '-ref', fixed, '-flo', moving, '-aff', output / 'transforms/registered.txt',
             '-cpp', registered, '-res', folder / 'registered.nii.gz', '-sx', '12', '-sy', '12', '-sz', '12',
             '-ln', '2', '-lp', '2', '-maxit', '3', '-omp', '1', '-voff'], log)
    entries.append(dict(id='nonlinear-registered-cpp', family='cubic-control-grid', representation='NREG_TRANS_TYPE=2',
                        transform=registered, transform_hint='niftyreg.cpp', origin='registered-native', domain='inputs/fixed.nii.gz'))
    composed = folder / 'affine-plus-nonlinear.nii.gz'
    command(['reg_transform', '-ref', fixed, '-comp', folder / 'deformation.nii.gz',
             output / 'transforms/registered.txt', composed, '-omp', '1'], log)
    entries.append(dict(id='nonlinear-affine-plus-field', family='affine-plus-field', representation='NREG_TRANS_TYPE=0',
                        transform=composed, transform_hint='niftyreg.deformation', origin='native-composition', domain='inputs/fixed.nii.gz'))
    return append_cases(output, entries, apply_image, unavailable=unavailable + [
        {'family': 'velocity-with-affine-extensions', 'reason': 'brainhops explicitly does not decode NiftyReg velocity affine extensions; native-integrated deformation is tested instead'},
        {'family': '2D-NREG-fields', 'reason': 'brainhops supports 3-component NREG fields only'},
    ])
