"""Native MRtrix dense, composed and bidirectional midway warp fixtures."""

from pathlib import Path

import nibabel as nib
import numpy as np

from brainhops_eval.files import read_json
from software._shared.affine import command
from software._shared.nonlinear import append_cases, smooth_displacement, world_grid


def apply_image(entry, moving, reference, degree, output, log):
    transform = entry['transform']
    if entry.get('displacement'):
        transform = output.parent / (output.stem + '-deformation.mif')
        command(['warpconvert', entry['transform'], 'displacement2deformation', transform, '-quiet'], log)
    args = ['mrtransform', moving, output, '-interp', 'linear' if degree else 'nearest',
            '-oversample', '1', '-datatype', 'float32', '-nthreads', '1', '-quiet']
    if entry.get('full'):
        args += ['-warp_full', transform, '-from', str(entry['from_image'])]
        args += ['-midway_space'] if entry.get('midway') else ['-template', reference]
    else:
        args += ['-warp', transform, '-template', reference]
    command(args, log)


def append(output):
    output = Path(output)
    folder = output / 'transforms/mrtrix-nonlinear'
    folder.mkdir()
    fixed, moving = output / 'inputs/fixed.nii.gz', output / 'inputs/moving.nii.gz'
    log = output / 'commands.log'
    entries = []
    image = nib.load(fixed)
    points = world_grid(image)
    known = folder / 'known-deformation.nii.gz'
    nib.save(nib.Nifti1Image((points + smooth_displacement(points)).astype(np.float32), image.affine), known)
    deformation = folder / 'known-deformation.mif'
    command(['mrconvert', known, deformation, '-quiet'], log)
    displacement = folder / 'known-displacement.mif'
    command(['warpconvert', deformation, 'deformation2displacement', displacement, '-quiet'], log)
    composed = folder / 'affine-plus-warp.mif'
    command(['transformcompose', output / 'transforms/registered.txt', deformation, composed,
             '-template', fixed, '-nthreads', '1', '-quiet'], log)
    for name, source, family, is_disp in [
        ('known-deformation', deformation, 'coordinates', False),
        ('known-displacement', displacement, 'displacements', True),
        ('affine-plus-warp', composed, 'affine-plus-warp-composed', False),
    ]:
        for extension in ('mif', 'mif.gz', 'mih'):
            path = source if extension == 'mif' else folder / f'{name}.{extension}'
            if path != source:
                command(['mrconvert', source, path, '-quiet'], log)
            entries.append(dict(id=f'nonlinear-{name}-{extension.replace(".", "-")}', family=family,
                                representation=extension, transform=path, displacement=is_disp,
                                transform_hint='mrtrix.displacement' if is_disp else 'mrtrix.coordinates',
                                origin='known-native', domain='inputs/fixed.nii.gz'))
    full = folder / 'registered-warpfull.mif'
    forward, inverse = folder / 'registered-forward.mif', folder / 'registered-inverse.mif'
    command(['mrregister', moving, fixed, '-type', 'affine_nonlinear',
             '-affine_init_matrix', output / 'transforms/registered.txt',
             '-affine_scale', '1', '-affine_niter', '5',
             '-nl_scale', '0.5,1', '-nl_niter', '3,2',
             '-nl_warp', forward, inverse, '-nl_warp_full', full, '-nthreads', '1', '-quiet'], log)
    for name, path in [('registered-forward', forward), ('registered-inverse', inverse)]:
        entries.append(dict(id='nonlinear-' + name, family=name, representation='mif',
                            transform=path, transform_hint='mrtrix.coordinates', origin='registered-native'))
    variants = read_json(output / 'inputs/inputs.json')['variants']
    for extension in ('mif', 'mih'):
        path = full if extension == 'mif' else folder / f'registered-warpfull.{extension}'
        if path != full:
            command(['mrconvert', full, path, '-quiet'], log)
        for direction in (1, 2):
            for midway in (False, True):
                entry = dict(id=f'nonlinear-warpfull-{extension}-from{direction}-' + ('midway' if midway else 'full'),
                             family='warpfull', representation=extension, transform=path,
                             transform_hint='mrtrix.warpfull', origin='registered-native', full=True,
                             from_image=direction, midway=midway,
                             transform_options={'from_image': direction, 'midway': midway})
                if midway:
                    reference = folder / f'midway-reference-from{direction}.nii.gz'
                    if not reference.exists():
                        command(['mrtransform', fixed, reference, '-warp_full', full, '-midway_space',
                                 '-from', str(direction), '-interp', 'linear', '-oversample', '1',
                                 '-datatype', 'float32', '-nthreads', '1', '-quiet'], log)
                    entry['reference'] = str(reference.relative_to(output))
                    entry['variants'] = [v for v in variants if v['id'] in ('native', 'moving-downsampled')]
                entries.append(entry)
    return append_cases(output, entries, apply_image)
