"""Native FNIRT spline, dense absolute/relative and composed warp fixtures."""

from pathlib import Path

import nibabel as nib
import numpy as np

from software._shared.affine import command, fsl_scaled
from software._shared.nonlinear import append_cases, smooth_displacement, world_grid


def apply_image(entry, source, reference, degree, output, log):
    root = Path(entry['root'])
    original_mov = nib.load(root / entry['transform_images']['moving'])
    original_ref = nib.load(root / entry['transform_images']['reference'])
    mov, ref = nib.load(source), nib.load(reference)
    pre = fsl_scaled(original_mov) @ np.linalg.inv(original_mov.affine) @ mov.affine @ np.linalg.inv(fsl_scaled(mov))
    post = fsl_scaled(ref) @ np.linalg.inv(ref.affine) @ original_ref.affine @ np.linalg.inv(fsl_scaled(original_ref))
    prefix = output.parent / output.name.removesuffix('.nii.gz')
    pre_path, post_path = Path(str(prefix) + '-pre.mat'), Path(str(prefix) + '-post.mat')
    np.savetxt(pre_path, pre, fmt='%.15g')
    np.savetxt(post_path, post, fmt='%.15g')
    warp = Path(str(prefix) + '-rebased.nii.gz')
    args = ['convertwarp', '--ref=' + str(reference), '--warp1=' + str(entry['transform']),
            '--premat=' + str(pre_path), '--postmat=' + str(post_path), '--relout', '--out=' + str(warp)]
    if entry.get('dense'):
        args.append('--abs' if entry.get('absolute') else '--rel')
    command(args, log)
    command(['applywarp', '--in=' + str(source), '--ref=' + str(reference), '--warp=' + str(warp),
             '--out=' + str(output), '--rel', '--interp=' + ('trilinear' if degree else 'nn'), '--datatype=float'], log)


def append(output):
    output = Path(output)
    folder = output / 'transforms/fsl-nonlinear'
    folder.mkdir()
    log = output / 'commands.log'
    fixed, moving = output / 'inputs/fixed.nii.gz', output / 'inputs/moving.nii.gz'
    ref, mov = nib.load(fixed), nib.load(moving)
    points = world_grid(ref)
    warped = points + smooth_displacement(points)
    to_mov = fsl_scaled(mov) @ np.linalg.inv(mov.affine)
    to_ref = fsl_scaled(ref) @ np.linalg.inv(ref.affine)
    absolute = warped @ to_mov[:3, :3].T + to_mov[:3, 3]
    relative = absolute - (points @ to_ref[:3, :3].T + to_ref[:3, 3])
    entries = []
    def entry(name, path, family, representation, **extra):
        return dict(id='nonlinear-' + name, family=family, representation=representation,
                    transform=path, root=output, transform_hint='fnirt',
                    transform_images={'moving': 'inputs/moving.nii.gz', 'reference': 'inputs/fixed.nii.gz'},
                    origin='registered-native' if 'registered' in name else 'known-native',
                    domain='inputs/fixed.nii.gz', **extra)
    for name, values, is_absolute in [('known-relative', relative, False), ('known-absolute', absolute, True)]:
        path = folder / (name + '.nii.gz')
        image = nib.Nifti1Image(values.astype(np.float32), ref.affine)
        image.header['intent_code'] = 0 if is_absolute else 2006
        image.header.set_xyzt_units('mm')
        nib.save(image, path)
        entries.append(entry(name, path, 'dense-' + ('absolute' if is_absolute else 'relative'), 'FNIRT field intent 0' if is_absolute else 'FNIRT field 2006',
                             dense=True, absolute=is_absolute,
                             transform_options={'deformation_type': 'absolute' if is_absolute else 'relative'}))
    for order in (2, 3):
        coeff = folder / f'registered-order{order}-coefficients.nii.gz'
        command(['fnirt', '--in=' + str(moving), '--ref=' + str(fixed),
                 '--aff=' + str(output / 'transforms/registered.mat'), '--cout=' + str(coeff),
                 '--warpres=12,12,12', '--splineorder=' + str(order), '--subsamp=2,1', '--miter=2,2',
                 '--infwhm=2,0', '--reffwhm=2,0', '--lambda=50,30', '--intmod=none', '--estint=0,0', '--applyrefmask=0,0', '--applyinmask=0,0'], log)
        entries.append(entry(f'registered-bspline{order}-with-affine', coeff, f'bspline-order{order}-with-affine',
                             'FNIRT coefficients 2009' if order == 2 else 'FNIRT coefficients 2007'))
        for convention in ('relative', 'absolute'):
            field = folder / f'registered-order{order}-{convention}.nii.gz'
            command(['convertwarp', '--ref=' + str(fixed), '--warp1=' + str(coeff),
                     '--out=' + str(field), '--relout' if convention == 'relative' else '--absout'], log)
            entries.append(entry(f'registered-bspline{order}-to-{convention}', field,
                                 f'bspline{order}-converted-{convention}', 'FNIRT field', dense=True,
                                 absolute=convention == 'absolute',
                                 transform_options={'deformation_type': convention}))
    composed = folder / 'composed-warp-and-affine.nii.gz'
    # Noncommuting affine and nonlinear composition, materialised by FSL.
    command(['convertwarp', '--ref=' + str(fixed), '--warp1=' + str(folder / 'known-relative.nii.gz'),
             '--rel', '--postmat=' + str(output / 'transforms/registered.mat'), '--relout',
             '--out=' + str(composed)], log)
    entries.append(entry('composed-warp-and-affine', composed, 'warp-plus-affine-composed', 'FNIRT field', dense=True,
                         transform_options={'deformation_type': 'relative'}))
    inverse = folder / 'known-inverse-relative.nii.gz'
    command(['invwarp', '--warp=' + str(folder / 'known-relative.nii.gz'),
             '--ref=' + str(moving), '--out=' + str(inverse)], log)
    entries.append(entry('known-inverse', inverse, 'inverse-dense-displacement', 'FNIRT field',
                         dense=True, transform_options={'deformation_type': 'relative'}))
    entries[-1]['transform_images'] = {'moving': 'inputs/fixed.nii.gz', 'reference': 'inputs/moving.nii.gz'}
    entries[-1]['domain'] = 'inputs/moving.nii.gz'
    result = append_cases(output, entries, apply_image, unavailable=[
        {'family': 'DCT-coefficients-2008', 'reason': 'brainhops detects but does not implement FNIRT DCT coefficient evaluation; FNIRT 6.0.4 exposes quadratic/cubic spline outputs'},
    ])
    validate_known_fields(output)
    return result


def validate_known_fields(output):
    """Check FSL's scaled-frame rebasing against independent RAS sampling."""
    from scipy.ndimage import map_coordinates
    from brainhops_eval.files import write_json
    from software._shared.nonlinear import aligned

    results = []
    for convention in ('absolute', 'relative'):
        for variant, filename in [('native', 'moving.nii.gz'), ('moving-downsampled', 'moving-downsampled.nii.gz')]:
            source = nib.load(output / 'inputs' / filename)
            reference = nib.load(output / 'inputs/fixed.nii.gz')
            points = world_grid(reference)
            points += smooth_displacement(points)
            inverse = np.linalg.inv(source.affine)
            voxels = points @ inverse[:3, :3].T + inverse[:3, 3]
            expected = map_coordinates(source.get_fdata(), np.moveaxis(voxels, -1, 0), order=1,
                                       mode='constant', cval=0, prefilter=False)
            folder = output / 'cases' / f'nonlinear-known-{convention}-{variant}'
            actual = aligned(folder / 'expected.nii.gz', output / 'inputs/fixed.nii.gz')
            mask = np.load(folder / 'interior.npy')
            error = float(np.max(abs(actual - expected)[mask]))
            if error > .01:
                raise ValueError(f'FSL known world-map check failed: {convention}/{variant}: {error}')
            results.append(dict(convention=convention, variant=variant, interior_max_abs=error, tolerance=.01))
    write_json(output / 'nonlinear-world-checks.json', results)
    # The independent checks are part of the immutable native artifact.
    from brainhops_eval.files import inventory
    write_json(output / 'manifest.json', {'schema_version': 1, 'files': inventory(output)})
