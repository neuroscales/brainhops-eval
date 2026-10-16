"""Native ITK transform-family fixtures shared by SimpleITK and ANTs recipes."""

from pathlib import Path

import nibabel as nib
import numpy as np
import SimpleITK as sitk
import subprocess

from .nonlinear import append_cases, smooth_displacement, world_grid


def read_transform(path):
    path = Path(path)
    if str(path).endswith('.nii.gz'):
        return sitk.DisplacementFieldTransform(sitk.ReadImage(str(path), sitk.sitkVectorFloat64))
    try:
        return sitk.ReadTransform(str(path))
    except KeyError as error:
        # SimpleITK 2.5 omits some transform IDs from its Python downcast map.
        # The native binding still returns a usable generic Transform.
        if error.args not in ((sitk.sitkQuaternionRigid,), (sitk.sitkComposeScaleSkewVersor,)):
            raise
        return sitk._SimpleITK.ReadTransform(str(path))


def transform_set(output):
    output = Path(output)
    fixed = nib.load(output / 'inputs/fixed.nii.gz')
    # Pad the physical domain so regridding does not immediately hit a field edge.
    shape = tuple(np.array(fixed.shape) + 16)
    affine = fixed.affine.copy()
    affine[:3, 3] -= affine[:3, :3] @ np.full(3, 8)
    domain_path = output / 'transforms/itk-domain.nii.gz'
    nib.save(nib.Nifti1Image(np.zeros(shape, np.float32), affine), domain_path)
    domain = sitk.ReadImage(str(domain_path))
    result = [('identity', sitk.Transform(3, sitk.sitkIdentity), 'identity')]
    for name, transform, params in [
        ('translation', sitk.TranslationTransform(3), [1.2, -.7, .4]),
        ('scale', sitk.ScaleTransform(3), [1.02, .98, 1.01]),
        ('scale-logarithmic', sitk.Transform(3, sitk.sitkScaleLogarithmic), np.log([1.02, .98, 1.01])),
        ('similarity3d', sitk.Similarity3DTransform(), [.01, -.02, .015, 1.2, -.7, .4, 1.02]),
        ('euler3d', sitk.Euler3DTransform(), [.02, -.03, .04, 1.2, -.7, .4]),
        ('versor', sitk.VersorTransform(), [.01, -.02, .015]),
        ('versor-rigid3d', sitk.VersorRigid3DTransform(), [.01, -.02, .015, 1.2, -.7, .4]),
        ('scale-versor3d', sitk.ScaleVersor3DTransform(), [.01, -.02, .015, 1.2, -.7, .4, 1.02, .98, 1.01]),
        ('scale-skew-versor3d', sitk.ScaleSkewVersor3DTransform(), [.01, -.02, .015, 1.2, -.7, .4, 1.02, .98, 1.01, .01, -.01, .02, -.01, .01, -.02]),
    ]:
        transform.SetParameters([float(v) for v in params])
        result.append((name, transform, name))
    quaternion = sitk.Transform(3, sitk.sitkQuaternionRigid)
    quaternion.SetParameters([.01, -.02, .015, float(np.sqrt(1 - .01**2 - .02**2 - .015**2)), 1.2, -.7, .4])
    result.append(('quaternion-rigid3d', quaternion, 'quaternion-rigid3d'))
    composed_skew = sitk.ComposeScaleSkewVersor3DTransform()
    composed_skew.SetRotation([1., 2., 3.], .04)
    composed_skew.SetTranslation([1.2, -.7, .4])
    composed_skew.SetScale([1.02, .98, 1.01])
    composed_skew.SetSkew([.01 * (-1)**i for i in range(len(composed_skew.GetSkew()))])
    result.append(('compose-scale-skew-versor3d', composed_skew, 'compose-scale-skew-versor3d'))
    # ITK's generic matrix-offset block is separate from AffineTransform.
    path = output / 'transforms/matrix-offset-source.tfm'
    path.write_text('#Insight Transform File V1.0\n#Transform 0\nTransform: MatrixOffsetTransformBase_double_3_3\nParameters: 1.02 0.01 0 0 0.98 0.02 0 0 1.01 1.2 -0.7 0.4\nFixedParameters: 0 0 0\n')
    matrix_offset = sitk.ReadTransform(str(path))
    if isinstance(matrix_offset, sitk.CompositeTransform):
        matrix_offset = matrix_offset.GetNthTransform(0)
    result.append(('matrix-offset', matrix_offset, 'matrix-offset'))
    for order in (0, 1, 2, 3):
        transform = sitk.BSplineTransformInitializer(domain, [3, 4, 3], order=order)
        values = np.arange(transform.GetNumberOfParameters(), dtype=float)
        transform.SetParameters((.7 * np.sin(values * .43) + .2 * np.cos(values * .17)).tolist())
        result.append((f'bspline-order{order}', transform, f'bspline-order{order}'))
    image = nib.load(domain_path)
    displacements = smooth_displacement(world_grid(image)) * [-1, -1, 1]
    field = sitk.GetImageFromArray(displacements.transpose(2, 1, 0, 3).copy(), isVector=True)
    field.CopyInformation(domain)
    displacement = sitk.DisplacementFieldTransform(sitk.Image(field))
    result.append(('displacement', displacement, 'dense-displacement'))
    inverse = sitk.InvertDisplacementField(field, maximumNumberOfIterations=30)
    result.append(('inverse-displacement', sitk.DisplacementFieldTransform(inverse), 'inverse-displacement'))
    composite = sitk.CompositeTransform(3)
    composite.AddTransform(sitk.Euler3DTransform([0., 0., 0.], .02, -.03, .04, [1.2, -.7, .4]))
    composite.AddTransform(result[-4][1])  # nonzero B-spline (order 2)
    composite.AddTransform(displacement)
    composite.FlattenTransform()
    result.append(('composite-affine-bspline-displacement', composite, 'composite'))
    # Noncommuting reverse order is a distinct composite, not another filename.
    reverse = sitk.CompositeTransform(3)
    for index in reversed(range(composite.GetNumberOfTransforms())):
        reverse.AddTransform(composite.GetNthTransform(index))
    result.append(('composite-reverse-order', reverse, 'composite-reverse-order'))
    return result


def entries(output, backend):
    output = Path(output)
    definitions, unavailable = [], []
    points = [(-9., 2., 0.), (10., -3., 3.), (-14., -12., 10.), (7., 14., -9.)]
    transforms = transform_set(output)
    if backend == 'simpleitk':
        fixed = sitk.ReadImage(str(output / 'inputs/fixed.nii.gz'), sitk.sitkFloat32)
        moving = sitk.ReadImage(str(output / 'inputs/moving.nii.gz'), sitk.sitkFloat32)
        affine = sitk.ReadTransform(str(output / 'transforms/registered.tfm'))
        spline = sitk.BSplineTransformInitializer(fixed, [3, 3, 3], order=3)
        method = sitk.ImageRegistrationMethod()
        method.SetMetricAsMeanSquares()
        method.SetInterpolator(sitk.sitkLinear)
        method.SetInitialTransform(spline, inPlace=True)
        method.SetMovingInitialTransform(affine)
        method.SetOptimizerAsRegularStepGradientDescent(.1, .005, 4)
        method.SetOptimizerScalesFromPhysicalShift()
        method.SetShrinkFactorsPerLevel([2, 1])
        method.SetSmoothingSigmasPerLevel([1, 0])
        method.Execute(fixed, moving)
        combined = sitk.CompositeTransform([affine, spline])
        transforms += [('registered-bspline', spline, 'registered-bspline'),
                       ('registered-affine-bspline', combined, 'registered-affine-bspline')]
    for name, transform, family in transforms:
        for extension in ('tfm', 'h5', 'mat'):
            path = output / 'transforms' / f'{name}.{extension}'
            # ITK's MATLAB IO cannot encode CompositeTransform containers.
            if extension == 'mat' and isinstance(transform, sitk.CompositeTransform):
                unavailable.append({'family': family, 'representation': 'mat', 'reason': 'ITK MATLAB transform IO cannot encode composite containers; tfm and h5 are tested'})
                continue
            sitk.WriteTransform(transform, str(path))
            back = read_transform(path)
            error = max(np.linalg.norm(np.array(transform.TransformPoint(p)) - back.TransformPoint(p)) for p in points)
            if error > 1e-8:
                raise ValueError(f'ITK serialization changed points: {path}: {error}')
            definitions.append(dict(id=f'type-{name}-{extension}', family=family, representation=extension,
                                    transform=path, transform_hint='itk', origin='registered-native' if name.startswith('registered-') else 'known-native',
                                    domain='transforms/itk-domain.nii.gz'))
        if name in ('displacement', 'inverse-displacement'):
            path = output / 'transforms' / f'{name}.nii.gz'
            sitk.WriteImage(transform.GetDisplacementField(), str(path))
            definitions.append(dict(id=f'type-{name}-nifti', family=family, representation='itk-vector-nifti',
                                    transform=path, transform_hint='itk.displacements', origin='known-native',
                                    domain='transforms/itk-domain.nii.gz'))
    unavailable.extend([
        {'family': 'time-varying-velocity', 'reason': 'brainhops does not integrate ANTs time-varying velocity fields; not reinterpreted as displacements'},
        {'family': 'MINC-transform', 'reason': 'ANTs --minc transform output is not supported by the brainhops ITK reader'},
    ])
    return definitions, unavailable


def append(output, backend, apply_image):
    definitions, unavailable = entries(output, backend)
    return append_cases(output, definitions, apply_image, unavailable=unavailable)


def append_png(output, backend, apply_2d):
    """Exercise the supported 2-D ITK classes on native non-square PNG inputs."""
    from brainhops_eval.files import inventory, read_json, write_json
    from software._shared.itk import geometry, model_array

    output = Path(output)
    fixed_path, moving_path = output / 'inputs/fixed.png', output / 'inputs/moving.png'
    fixed = sitk.ReadImage(str(fixed_path), sitk.sitkFloat32)
    folder = output / 'transforms/itk-2d'
    folder.mkdir()
    transforms = []
    for name, transform, values in [
        ('identity', sitk.Transform(2, sitk.sitkIdentity), []),
        ('translation', sitk.TranslationTransform(2), [-3., 2.]),
        ('scale', sitk.ScaleTransform(2), [1.02, .98]),
        ('scale-logarithmic', sitk.Transform(2, sitk.sitkScaleLogarithmic), list(np.log([1.02, .98]))),
        ('euler2d', sitk.Euler2DTransform(), [.03, -3., 2.]),
        ('similarity2d', sitk.Similarity2DTransform(), [1.02, .03, -3., 2.]),
        ('affine', sitk.AffineTransform(2), [1.02, .01, -.01, .98, -3., 2.]),
    ]:
        transform.SetParameters(values)
        transforms.append((name, transform))
    for order in (0, 1, 2, 3):
        transform = sitk.BSplineTransformInitializer(fixed, [4, 3], order=order)
        transform.SetParameters((.7 * np.sin(np.arange(transform.GetNumberOfParameters()) * .37)).tolist())
        transforms.append((f'bspline-order{order}', transform))
    yy, xx = np.indices(tuple(reversed(fixed.GetSize())), dtype=float)
    vectors = np.stack([.8 * np.sin(yy / 12), .6 * np.cos(xx / 17)], axis=-1)
    field = sitk.GetImageFromArray(vectors, isVector=True)
    field.CopyInformation(fixed)
    displacement = sitk.DisplacementFieldTransform(field)
    transforms.append(('displacement', displacement))
    transforms.append(('composite-affine-bspline', sitk.CompositeTransform([transforms[6][1], transforms[10][1]])))
    manifest = read_json(output / 'cases.json')
    coverage = read_json(output / 'coverage.json')
    probes = read_json(output / 'geometry-probes.json')
    # Probe each backend through its own identity application and encoded output
    # geometry, rather than attributing SimpleITK's defaults to ANTs.
    identity = folder / 'probe.tfm'
    sitk.WriteTransform(sitk.Transform(2, sitk.sitkIdentity), str(identity))
    observed = {}
    for role, source in [('moving', moving_path), ('reference', fixed_path)]:
        path = folder / (role + '-probe.nii.gz')
        apply_2d(identity, source, source, 1, path, output / 'commands.log')
        native = sitk.ReadImage(str(path))
        observed[role] = geometry(native)
    probes['png'] = observed
    for name, transform in transforms:
        for extension in ('tfm', 'h5', 'mat'):
            if extension == 'mat' and isinstance(transform, sitk.CompositeTransform):
                coverage['unavailable'].append(dict(family=f'2d-{name}', representation=extension,
                                                    reason='ITK MATLAB transform IO cannot encode composite containers; tfm and h5 are tested'))
                continue
            path = folder / f'{name}.{extension}'
            sitk.WriteTransform(transform, str(path))
            case_dir = output / 'cases' / f'type-2d-{name}-{extension}'
            case_dir.mkdir()
            native_path = case_dir / 'expected.nii.gz'
            try:
                apply_2d(path, moving_path, fixed_path, 1, native_path, output / 'commands.log')
            except (subprocess.CalledProcessError, RuntimeError) as error:
                # Native factory omissions are captured as capability failures;
                # failed brainhops applications are never routed through here.
                text = (getattr(error, 'output', None) or str(error)).lower()
                if not any(token in text for token in ('could not create an instance', 'not registered', 'not supported')):
                    raise
                coverage['unavailable'].append(dict(family=f'2d-{name}', representation=extension,
                                                    reason=f'{backend} native reader rejected this 2-D type',
                                                    native_error=(getattr(error, 'output', None) or str(error))[:1800]))
                continue
            np.save(case_dir / 'expected.npy', model_array(sitk.ReadImage(str(native_path))))
            source = sitk.ReadImage(str(moving_path), sitk.sitkFloat32)
            support = np.zeros(tuple(reversed(source.GetSize())), np.float32)
            support[2:-2, 2:-2] = 1
            mask_image = sitk.GetImageFromArray(support)
            mask_image.CopyInformation(source)
            mask_path = case_dir / 'source-mask.nii.gz'
            sitk.WriteImage(mask_image, str(mask_path))
            mask_output = case_dir / 'mask.nii.gz'
            apply_2d(path, mask_path, fixed_path, 0, mask_output, output / 'commands.log')
            np.save(case_dir / 'interior.npy', model_array(sitk.ReadImage(str(mask_output))) > .999)
            case = dict(id=case_dir.name, kind='png', degree=1, moving='inputs/moving.png', reference='inputs/fixed.png',
                        transform=str(path.relative_to(output)), transform_hint='itk',
                        transform_family='2d-' + name, transform_representation=extension, transform_origin='known-native',
                        expected=str((case_dir / 'expected.npy').relative_to(output)),
                        mask=str((case_dir / 'interior.npy').relative_to(output)), display_window=[0, 255])
            manifest['cases'].append(case)
            coverage['tested'].append(dict(id=case['id'], family=case['transform_family'], representation=extension,
                                          origin='known-native', transform=case['transform'], cases=[case['id']]))
    write_json(output / 'cases.json', manifest)
    write_json(output / 'geometry-probes.json', probes)
    write_json(output / 'coverage.json', coverage)
    write_json(output / 'manifest.json', {'schema_version': 1, 'files': inventory(output)})
    return output
