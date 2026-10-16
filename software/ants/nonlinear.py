"""Native ANTs SyN fields, inverse fields, spline files and composites."""

from pathlib import Path
import subprocess

from software._shared.affine import command
from software._shared.itk_types import entries as itk_entries
from software._shared.nonlinear import append_cases


def apply_image(entry, source, reference, degree, output, log):
    command(['antsApplyTransforms', '-d', '3', '--float', '1', '-i', source, '-r', reference,
             '-t', entry['transform'], '-n', 'Linear' if degree else 'NearestNeighbor', '-o', output], log)


def append(output):
    output = Path(output)
    entries, unavailable = itk_entries(output, 'ants')
    # A native reader preflight distinguishes unsupported ANTs factory types
    # from a brainhops application failure, without dropping supported cases.
    supported = []
    folder = output / 'transforms/ants-nonlinear'
    folder.mkdir()
    fixed, moving = output / 'inputs/fixed.nii.gz', output / 'inputs/moving.nii.gz'
    log = output / 'commands.log'
    probe = folder / 'reader-probe.nii.gz'
    for entry in entries:
        try:
            apply_image(entry, fixed, fixed, 1, probe, log)
        except subprocess.CalledProcessError as error:
            text = error.output or ''
            if not any(token in text.lower() for token in ('could not create', 'not registered', 'not supported')):
                raise
            unavailable.append(dict(family=entry['family'], representation=entry['representation'],
                                    reason='ANTs native transform reader rejected this serialization',
                                    native_error=text[:1800], command_log='commands.log'))
            continue
        supported.append(entry)
    prefix = folder / 'syn-'
    affine = output / 'transforms/ants-0GenericAffine.mat'
    command(['antsRegistration', '--dimensionality', '3', '--float', '1', '--output', str(prefix),
             '--initial-moving-transform', affine, '--transform', 'SyN[0.1,3,0]',
             '--metric', f'MeanSquares[{fixed},{moving},1,0]', '--convergence', '[5x3,1e-6,3]',
             '--shrink-factors', '2x1', '--smoothing-sigmas', '1x0mm', '--random-seed', '1729',
             '--write-composite-transform', '0'], log)
    warps = [('syn-forward', Path(str(prefix) + '1Warp.nii.gz')),
             ('syn-inverse', Path(str(prefix) + '1InverseWarp.nii.gz'))]
    for name, path in warps:
        if not path.exists():
            raise ValueError(f'ANTs did not produce its native nonlinear field: {path}')
        supported.append(dict(id='nonlinear-' + name, family=name, representation='ANTs vector NIfTI',
                              transform=path, transform_hint='ants.displacements', origin='registered-native',
                              domain='inputs/fixed.nii.gz'))
    # Native ANTs creates the HDF5 container; noncommuting orders are both tested.
    for name, paths in [('affine-then-syn', [affine, warps[0][1]]),
                        ('syn-then-affine', [warps[0][1], affine])]:
        composite = folder / (name + '.h5')
        command(['CompositeTransformUtil', '--assemble', composite, *paths], log)
        supported.append(dict(id='nonlinear-' + name, family='composite-' + name,
                              representation='ANTs Composite.h5', transform=composite,
                              transform_hint='ants', origin='native-composition', domain='inputs/fixed.nii.gz'))
    result = append_cases(output, supported, apply_image, unavailable=unavailable)
    from software._shared.itk_types import append_png

    def apply_2d(transform, source, reference, degree, target, log):
        command(['antsApplyTransforms', '-d', '2', '--float', '1', '-i', source, '-r', reference,
                 '-t', transform, '-n', 'Linear' if degree else 'NearestNeighbor', '-o', target], log)

    return append_png(result, 'ants', apply_2d)
