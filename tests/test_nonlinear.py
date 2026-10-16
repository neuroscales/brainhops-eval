"""Check physical maps and representation semantics independently of brainhops."""
import shutil
from types import SimpleNamespace

import nibabel as nib
import numpy as np
import SimpleITK as sitk

from brainhops_eval.evaluate import load_transform, transform_source
from brainhops_eval.report import write_report
from software._shared.itk_types import read_transform, transform_set
from software._shared.nonlinear import smooth_displacement, world_grid


def test_native_fields_and_noncommuting_composites(inputs, tmp_path):
    shutil.copytree(inputs, tmp_path / 'inputs')
    (tmp_path / 'transforms').mkdir()
    transforms = {name: transform for name, transform, _ in transform_set(tmp_path)}
    domain = nib.load(tmp_path / 'transforms/itk-domain.nii.gz')
    ras = world_grid(domain)[10, 12, 14]
    lps = ras * [-1, -1, 1]
    expected = (ras + smooth_displacement(ras)) * [-1, -1, 1]
    np.testing.assert_allclose(transforms['displacement'].TransformPoint(lps), expected, atol=1e-8)
    # A second difference detects a genuinely nonlinear map, unlike a rotation.
    points = [np.array([x, 2., 3.]) for x in (-15., 0., 15.)]
    for name in ('displacement', 'bspline-order1', 'bspline-order2', 'bspline-order3'):
        mapped = np.array([transforms[name].TransformPoint(p) for p in points])
        assert np.linalg.norm(mapped[0] - 2 * mapped[1] + mapped[2]) > 1e-4
    direct = transforms['composite-affine-bspline-displacement']
    reverse = transforms['composite-reverse-order']
    assert np.linalg.norm(np.array(direct.TransformPoint(lps)) - reverse.TransformPoint(lps)) > .001
    # Each native encoding must preserve the physical map, including spline order.
    for name in ('bspline-order0', 'bspline-order2', 'displacement', 'compose-scale-skew-versor3d'):
        for extension in ('tfm', 'h5', 'mat'):
            path = tmp_path / f'{name}.{extension}'
            sitk.WriteTransform(transforms[name], str(path))
            np.testing.assert_allclose(read_transform(path).TransformPoint(lps),
                                       transforms[name].TransformPoint(lps), atol=1e-8)


def test_options_reach_python_and_cli_without_replacing_images(tmp_path):
    (tmp_path / 'warp.mif').touch()
    (tmp_path / 'moving.nii.gz').touch()
    original = object()
    calls = []
    bio = SimpleNamespace(images=SimpleNamespace(load=lambda path: original),
                          load=lambda path, **kw: calls.append(kw))
    case = {'transform': 'warp.mif', 'transform_hint': 'mrtrix',
            'transform_images': {'moving': 'moving.nii.gz'},
            'transform_options': {'from_image': 2, 'midway': False}}
    load_transform(bio, tmp_path, case)
    assert calls[0]['moving'] is original
    assert calls[0]['from_image'] == 2 and calls[0]['midway'] is False
    spec = transform_source(tmp_path, case)
    assert '|from_image:2|midway:false' in spec
    assert '|moving:[' in spec


def test_report_distinguishes_tested_native_representations_and_unavailable(tmp_path):
    result = dict(cases=[], brainhops_ref='test', brainhops_sha='sha', brainhops_version='version',
                  backend='native', interface='python', transform_coverage={
                      'tested': [dict(family='bspline', representation='h5', origin='known-native', cases=['a'])],
                      'unavailable': [dict(family='velocity', reason='native reader unavailable')]})
    write_report(tmp_path, result)
    report = (tmp_path / 'index.html').read_text()
    assert 'coverage.json' in report and 'bspline' in report
    assert 'native reader unavailable' in report
    assert 'inspect each comparison status' in report
