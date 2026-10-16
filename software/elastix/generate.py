"""Run elastix affine registration and transformix on each output grid."""

import os
from pathlib import Path
import re

import nibabel as nib
import numpy as np

from software._shared.affine import build, command, main


def parameters(path):
    result = {}
    for key, values in re.findall(r'\((\w+)\s+([^)]*)\)', Path(path).read_text()):
        result[key] = re.findall(r'"[^"]*"|[^\s]+', values)
    return result


def save_parameters(path, values):
    Path(path).write_text("\n".join(f"({key} {' '.join(map(str, value))})" for key, value in values.items()) + "\n")
    return path


def pull_from_parameters(path):
    values = parameters(path)
    if values['InitialTransformParametersFileName'] != ['"NoInitialTransform"']:
        raise ValueError("Unexpected chained registration transform")
    data = np.array(values['TransformParameters'], dtype=float)
    centre = np.array(values['CenterOfRotationPoint'], dtype=float)
    matrix = np.eye(4)
    matrix[:3, :3] = data[:9].reshape(3, 3)
    matrix[:3, 3] = data[9:] + centre - matrix[:3, :3] @ centre
    flip = np.diag([-1., -1., 1., 1.])
    return flip @ matrix @ flip


def write_transform(path, pull, moving, reference):
    ref = nib.load(reference)
    flip = np.diag([-1., -1., 1., 1.])
    lps = flip @ pull @ flip
    geometry = flip @ ref.affine
    spacing = np.linalg.norm(geometry[:3, :3], axis=0)
    direction = geometry[:3, :3] / spacing
    return save_parameters(path, {
        'Transform': ['"AffineTransform"'], 'NumberOfParameters': [12],
        'TransformParameters': [*lps[:3, :3].ravel(), *lps[:3, 3]],
        'InitialTransformParametersFileName': ['"NoInitialTransform"'],
        'HowToCombineTransforms': ['"Compose"'], 'FixedImageDimension': [3],
        'MovingImageDimension': [3], 'FixedInternalImagePixelType': ['"float"'],
        'MovingInternalImagePixelType': ['"float"'], 'CenterOfRotationPoint': [0, 0, 0],
        'Size': list(ref.shape), 'Index': [0, 0, 0], 'Spacing': list(spacing),
        'Origin': list(geometry[:3, 3]), 'Direction': list(direction.T.ravel()),
        'UseDirectionCosines': ['"true"'], 'ResampleInterpolator': ['"FinalBSplineInterpolator"'],
        'FinalBSplineInterpolationOrder': [1], 'Resampler': ['"DefaultResampler"'],
        'DefaultPixelValue': [0], 'ResultImageFormat': ['"nii.gz"'],
        'ResultImagePixelType': ['"float"'], 'CompressResultImage': ['"true"']})


def register(moving, reference, transforms, log):
    settings = Path(__file__).with_name('registration.txt')
    version = command(['elastix', '--version'], log)
    folder = transforms / 'registration'
    folder.mkdir()
    command(['elastix', '-f', reference, '-m', moving, '-p', settings,
             '-out', folder, '-threads', '1'], log)
    path = folder / 'TransformParameters.0.txt'
    return pull_from_parameters(path), path, {
        'version': version, 'algorithm': 'elastix affine', 'metric': 'AdvancedMeanSquares',
        'optimizer': 'AdaptiveStochasticGradientDescent', 'resolutions': 2,
        'max_iterations': 100, 'sampler': 'Full',
        'parameter_file': settings.read_text()}


def apply_image(moving, reference, transform, degree, output, log):
    values = parameters(transform)
    values['FinalBSplineInterpolationOrder'] = [str(degree)]
    save_parameters(transform, values)
    folder = output.parent / 'transformix'
    folder.mkdir()
    command(['transformix', '-in', moving, '-tp', transform, '-out', folder, '-threads', '1'], log)
    (folder / 'result.nii.gz').replace(output)


def generate(inputs, output, container_image=None):
    os.environ['ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS'] = '1'
    result = build(inputs, output, backend='elastix', register=register,
                 write_transform=write_transform, apply_image=apply_image, hint='elastix',
                 convention='elastix/transformix: fixed physical LPS mm to moving physical LPS mm (pull)',
                 container_image=container_image)
    from software.elastix.nonlinear import append
    return append(result)


if __name__ == '__main__':
    main(generate)
