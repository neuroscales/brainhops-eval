"""Native elastix transform classes, spline orders and chained parameter files."""

from pathlib import Path
import subprocess

import numpy as np

from software._shared.affine import command
from software._shared.nonlinear import append_cases
from software.elastix.generate import parameters, save_parameters, write_transform


def apply_image(entry, source, reference, degree, output, log):
    original = Path(entry['transform'])
    values = parameters(original)
    geometry_file = output.parent / (output.name + '-geometry.txt')
    write_transform(geometry_file, np.eye(4), source, reference)
    geometry = parameters(geometry_file)
    for key in ('Size', 'Index', 'Spacing', 'Origin', 'Direction'):
        values[key] = geometry[key]
    values['FinalBSplineInterpolationOrder'] = [str(degree)]
    initial = values.get('InitialTransformParametersFileName', ['"NoInitialTransform"'])[0].strip('"')
    if initial != 'NoInitialTransform':
        values['InitialTransformParametersFileName'] = ['"' + str((original.parent / initial).resolve()) + '"']
    path = output.parent / (output.name + '-parameters.txt')
    save_parameters(path, values)
    folder = output.parent / (output.name + '-transformix')
    folder.mkdir()
    command(['transformix', '-in', source, '-tp', path, '-out', folder, '-threads', '1'], log,
            cwd=original.parent)
    (folder / 'result.nii.gz').replace(output)


def append(output):
    output = Path(output)
    folder = output / 'transforms/elastix-types'
    folder.mkdir()
    fixed, moving = output / 'inputs/fixed.nii.gz', output / 'inputs/moving.nii.gz'
    log = output / 'commands.log'
    template = folder / 'template.txt'
    write_transform(template, np.eye(4), moving, fixed)
    base = parameters(template)
    entries, unavailable = [], []
    paths = {}
    def add(name, transform, values, family=None, origin='known-native'):
        record = dict(base)
        record.update(values)
        record['Transform'] = ['"' + transform + '"']
        path = save_parameters(folder / (name + '.txt'), record)
        entry = dict(id='type-' + name, family=family or transform, representation='elastix parameter file',
                     transform=path, transform_hint='elastix', origin=origin, domain='inputs/fixed.nii.gz')
        paths[name] = path
        entries.append(entry)
        return path
    for name, transform, data in [
        ('translation', 'TranslationTransform', [1.2, -.7, .4]),
        ('euler-zyx0', 'EulerTransform', [.02, -.03, .04, 1.2, -.7, .4]),
        ('euler-zyx1', 'EulerTransform', [.02, -.03, .04, 1.2, -.7, .4]),
        ('similarity', 'SimilarityTransform', [.01, -.02, .015, 1.2, -.7, .4, 1.02]),
        ('affine', 'AffineTransform', [1.02, .01, 0, 0, .98, .02, 0, 0, 1.01, 1.2, -.7, .4]),
        ('affine-log', 'AffineLogTransform', [.02, .01, 0, 0, -.02, .02, 0, 0, .01, 1.2, -.7, .4]),
        ('affine-dti', 'AffineDTITransform', [.02, -.03, .04, .01, -.02, .01, 1.02, .98, 1.01, 1.2, -.7, .4]),
    ]:
        add(name, transform, {'NumberOfParameters': [len(data)], 'TransformParameters': data,
                              'ComputeZYX': ['"true"' if name.endswith('zyx1') else '"false"']})
    for transform in ('BSplineTransform', 'RecursiveBSplineTransform'):
        for order in (1, 2, 3):
            shape = (13, 13, 13)
            values = .7 * np.sin(np.arange(np.prod(shape) * 3) * .037) + .3 * np.cos(np.arange(np.prod(shape) * 3) * .011)
            add(f'{transform.lower()}-order{order}', transform, {
                'NumberOfParameters': [len(values)], 'TransformParameters': list(values),
                'BSplineTransformSplineOrder': [order], 'GridSize': list(shape), 'GridIndex': [0, 0, 0],
                'GridSpacing': [10, 10, 10], 'GridOrigin': [-60, -60, -60],
                'GridDirection': list(np.eye(3).ravel()), 'UseCyclicTransform': ['"false"'],
            }, family=f'{transform}-order{order}')
    bspline = parameters(paths['bsplinetransform-order3'])
    for mode in ('Compose', 'Add'):
        values = dict(bspline)
        values['InitialTransformParametersFileName'] = ['"affine.txt"']
        values['HowToCombineTransforms'] = ['"' + mode + '"']
        add('affine-plus-bspline-' + mode.lower(), 'BSplineTransform', values, family='chained-' + mode.lower())
    # A second chain stage ensures recursive relative-file resolution is tested.
    values = parameters(paths['affine-plus-bspline-compose'])
    values['InitialTransformParametersFileName'] = ['"affine-plus-bspline-compose.txt"']
    add('nested-three-stage', 'BSplineTransform', values, family='chained-three-stage')
    # Native multiresolution B-spline estimation, initialised by the actual affine registration.
    settings = (Path(__file__).parent / 'registration.txt').read_text().replace('"AffineTransform"', '"BSplineTransform"')
    settings = settings.replace('(MaximumNumberOfIterations 100)', '(MaximumNumberOfIterations 4)')
    settings += '\n(FinalGridSpacingInPhysicalUnits 12.0)\n'
    config = folder / 'registration-bspline.txt'
    config.write_text(settings)
    registration = folder / 'registration'
    registration.mkdir()
    command(['elastix', '-f', fixed, '-m', moving, '-p', config,
             '-t0', output / 'transforms/registration/TransformParameters.0.txt',
             '-out', registration, '-threads', '1'], log)
    estimated = parameters(registration / 'TransformParameters.0.txt')
    estimated['InitialTransformParametersFileName'] = ['"../registration/TransformParameters.0.txt"']
    path = save_parameters(folder / 'registered-bspline-chain.txt', estimated)
    entries.append(dict(id='nonlinear-registered-bspline-chain', family='registered-affine-bspline-chain',
                        representation='elastix parameter chain', transform=path, transform_hint='elastix',
                        origin='registered-native', domain='inputs/fixed.nii.gz'))
    # Capability preflight records missing native factory components explicitly.
    accepted = []
    probe_dir = folder / 'probes'
    probe_dir.mkdir()
    for entry in entries:
        target = probe_dir / (entry['id'] + '.nii.gz')
        try:
            apply_image(entry, moving, fixed, 1, target, log)
        except subprocess.CalledProcessError as error:
            text = error.output or ''
            if not any(token in text for token in ('does not exist', 'Could not create', 'not installed', 'not supported')):
                raise
            unavailable.append(dict(family=entry['family'], reason='Native elastix factory rejected this type',
                                    native_error=text[-1500:], command_log='commands.log'))
            continue
        accepted.append(entry)
    return append_cases(output, accepted, apply_image, unavailable=unavailable + [
        {'family': 'cyclic-bspline', 'reason': 'brainhops explicitly rejects UseCyclicTransform; it is not treated as an ordinary B-spline'},
    ])
