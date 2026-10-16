"""Generate native SimpleITK registration and resampling fixtures."""

import SimpleITK as sitk

from software._shared.itk import build, main, read_image


def register(fixed, moving):
    initial = sitk.CenteredTransformInitializer(
        fixed, moving, sitk.Euler3DTransform(),
        sitk.CenteredTransformInitializerFilter.GEOMETRY,
    )
    method = sitk.ImageRegistrationMethod()
    method.SetMetricAsMeanSquares()
    method.SetMetricSamplingStrategy(method.NONE)
    method.SetInterpolator(sitk.sitkLinear)
    method.SetOptimizerAsRegularStepGradientDescent(
        learningRate=1, minStep=0.001, numberOfIterations=120,
        gradientMagnitudeTolerance=1e-6,
    )
    method.SetOptimizerScalesFromPhysicalShift()
    method.SetShrinkFactorsPerLevel([2, 1])
    method.SetSmoothingSigmasPerLevel([1, 0])
    method.SmoothingSigmasAreSpecifiedInPhysicalUnitsOn()
    method.SetInitialTransform(initial, inPlace=True)
    method.Execute(fixed, moving)
    # Flatten rigid output into an affine to exercise broad file interoperability.
    affine = sitk.AffineTransform(3)
    affine.SetCenter(initial.GetCenter())
    affine.SetMatrix(initial.GetMatrix())
    affine.SetTranslation(initial.GetTranslation())
    return affine, {"metric": method.GetMetricValue(),
                    "stop_condition": method.GetOptimizerStopConditionDescription(),
                    "optimizer": "RegularStepGradientDescent", "iterations": 120,
                    "metric_name": "MeanSquares", "shrink_factors": [2, 1],
                    "smoothing_sigmas_mm": [1, 0], "sampling": "all voxels"}


def register_inputs(inputs, transforms, output):
    estimated, metadata = register(read_image(inputs / "fixed.nii.gz"),
                                   read_image(inputs / "moving.nii.gz"))
    return estimated, metadata, {}


def apply_image(source, reference, transform, degree, output, log):
    result = sitk.Resample(read_image(source), read_image(reference),
                           sitk.ReadTransform(str(transform)),
                           sitk.sitkLinear if degree else sitk.sitkNearestNeighbor,
                           0, sitk.sitkFloat32)
    sitk.WriteImage(result, str(output))


def generate(inputs, output, container_image=None, extended=True):
    """Generate SimpleITK references from a shared input bundle."""
    result = build(inputs, output, backend="simpleitk", register=register_inputs,
                 apply_image=apply_image, include_rasters=True,
                 container_image=container_image)
    if not extended:
        return result
    from software._shared.itk_types import append, read_transform

    def apply_entry(entry, source, reference, degree, target, log):
        resampled = sitk.Resample(read_image(source), read_image(reference),
                                  read_transform(entry['transform']),
                                  sitk.sitkLinear if degree else sitk.sitkNearestNeighbor,
                                  0, sitk.sitkFloat32)
        sitk.WriteImage(resampled, str(target))

    result = append(result, 'simpleitk', apply_entry)
    from software._shared.itk_types import append_png

    def apply_2d(transform, source, reference, degree, target, log):
        resampled = sitk.Resample(read_image(source), read_image(reference), read_transform(transform),
                                  sitk.sitkLinear if degree else sitk.sitkNearestNeighbor, 0, sitk.sitkFloat32)
        sitk.WriteImage(resampled, str(target))

    return append_png(result, 'simpleitk', apply_2d)


if __name__ == "__main__":
    main(generate)
