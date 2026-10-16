import shutil

import nibabel as nib
import numpy as np
from PIL import Image
import pytest

from brainhops_eval.evaluate import expected_on_reference_grid, load_transform, transform_source
from brainhops_eval.report import montage
from software._shared.affine import flirt_from_pull


def test_montage_uses_one_explicit_intensity_window(tmp_path):
    path = tmp_path / 'montage.png'
    reference = np.full((10, 10), 20.)
    expected = np.full((10, 10), 40.)
    actual = np.full((10, 10), 40.)
    montage(path, reference, expected, actual, window=[0, 100])
    image = Image.open(path)
    assert image.getpixel((95, 120)) == (51, 51, 51)
    for column in (1, 2, 3):
        assert image.getpixel((column * 190 + 95, 120)) == (102, 102, 102)


def test_native_output_permutation_is_lossless_and_wrong_grid_rejected(tmp_path):
    values = np.arange(3 * 4 * 5, dtype=np.float32).reshape(3, 4, 5)
    reference = nib.Nifti1Image(values, np.diag([2., 3., 4., 1.]))
    nib.save(reference, tmp_path / 'reference.nii.gz')
    changed = reference.as_reoriented(np.array([[1, -1], [2, 1], [0, -1]]))
    nib.save(changed, tmp_path / 'native.nii.gz')
    aligned, orientation = expected_on_reference_grid(tmp_path / 'native.nii.gz', tmp_path / 'reference.nii.gz')
    np.testing.assert_array_equal(aligned, values)
    changed.affine[0, 3] += 0.5
    nib.save(changed, tmp_path / 'wrong.nii.gz')
    with pytest.raises(ValueError, match='reference grid'):
        expected_on_reference_grid(tmp_path / 'wrong.nii.gz', tmp_path / 'reference.nii.gz')


def test_flirt_keeps_original_geometry_when_applying_to_another_grid(inputs, tmp_path):
    import brainhops.io as bio
    from brainhops.io.base import TransformationSpec

    shutil.copytree(inputs, tmp_path / "inputs")
    inputs = tmp_path / "inputs"
    pull = np.eye(4)
    pull[:3, 3] = [3, -2, 1]
    matrix = flirt_from_pull(pull, inputs / 'moving.nii.gz', inputs / 'fixed.nii.gz')
    np.savetxt(inputs / 'test-flirt.mat', matrix)
    case = {'transform': 'test-flirt.mat', 'transform_hint': 'flirt',
            'moving': 'moving-downsampled.nii.gz', 'reference': 'reference-oblique.nii.gz',
            'transform_images': {'moving': 'moving.nii.gz', 'reference': 'fixed.nii.gz'}}
    transform = load_transform(bio, inputs, case)
    np.testing.assert_allclose(transform.matrix, pull[:3], atol=3e-6)
    # CLI and Python decode the same options, including nested image sources.
    spec = TransformationSpec.from_arg(transform_source(inputs, case))
    cli_transform = bio.transformations.load(spec)
    np.testing.assert_allclose(cli_transform.matrix, pull[:3], atol=3e-6)
