"""Check human explanations, offline reports, and versioned artifact publication."""
import json
from pathlib import Path

import numpy as np
import pytest

from brainhops_eval.comparison import assess, conclude
from brainhops_eval.files import write_json
from brainhops_eval.report import write_report
from brainhops_eval.site import build_site


def _result(case, backend='simpleitk', sha='commit-123'):
    return dict(cases=[case], backend=backend, interface='python', brainhops_ref='main',
                brainhops_sha=sha, brainhops_version='test', passed=case['status'] in ('pass', 'warning'),
                registration={})


def _case(actual, expected, mask):
    record, _ = assess(actual, expected, mask, degree=1)
    record.update(id='example', transform='transform.tfm', axis_interpretation={})
    conclude(record)
    return record


def test_report_explains_integer_failure_and_limits(tmp_path):
    actual = np.zeros((4, 4), np.int16)
    actual[1, 1] = 1
    record = _case(actual, np.zeros((4, 4)), np.ones((4, 4), bool))
    record['warnings'] = ['<script>alert("unsafe")</script>']
    assert record['status'] == 'fail'
    assert '1 of 16 interior voxels differ' in record['summary']
    write_report(tmp_path, _result(record))
    index = (tmp_path / 'index.html').read_text()
    detail = (tmp_path / 'example/index.html').read_text()
    assert 'Why this result?' in index and 'exact int16 equality' in index
    assert 'Observed' in detail and 'Required' in detail
    assert '<script>alert' not in detail and '&lt;script&gt;' in detail
    assert (tmp_path / 'report.css').exists() and (tmp_path / 'report.js').exists()


def test_nrmse_can_fail_when_maximum_passes():
    actual = np.full((4, 4), .001, np.float32)
    record = _case(actual, np.zeros((4, 4)), np.ones((4, 4), bool))
    assert record['status'] == 'fail'
    assert record['metrics']['interior_max_abs'] < record['metrics']['atol']
    assert [reason['code'] for reason in record['diagnostics']] == ['normalised-rmse']
    assert 'NRMSE' in record['summary']


def test_axes_can_fail_even_when_values_match():
    record = _case(np.zeros((4, 4)), np.zeros((4, 4)), np.ones((4, 4), bool))
    record['axis_interpretation'] = {'moving': {'checks': {'pixels_match_package_axis_order': False}}}
    conclude(record)
    assert record['status'] == 'fail' and 'axis order failed' in record['summary']


def test_boundary_diagnostics_do_not_hide_an_interior_failure():
    actual, expected = np.zeros((5, 5)), np.zeros((5, 5))
    mask = np.zeros((5, 5), bool)
    mask[1:-1, 1:-1] = True
    actual[0, 0] = 100
    record = _case(actual, expected, mask)
    assert record['status'] == 'warning'
    actual[2, 2] = 10
    record = _case(actual, expected, mask)
    assert record['status'] == 'fail'
    assert {'boundary', 'interior'} == {reason['scope'] for reason in record['diagnostics']}


def _artifact(root: Path, backend='simpleitk', sha='commit-123'):
    root.mkdir(parents=True)
    case = _case(np.zeros((4, 4)), np.zeros((4, 4)), np.ones((4, 4), bool))
    result = _result(case, backend, sha)
    write_json(root / 'results.json', result)
    write_json(root / 'registration.json', {})
    write_report(root, result)
    (root / 'example/brainhops.nii.gz').write_bytes(b'full resliced image stays in Actions')
    return result


def test_site_publishes_failed_reports_without_full_images(tmp_path):
    reports, site = tmp_path / 'reports', tmp_path / 'site'
    result = _artifact(reports / 'first')
    result['cases'][0].update(status='error', summary='Read transform failed: unsupported type',
                              error='traceback details', error_summary='Unsupported transform type')
    result['passed'] = False
    write_json(reports / 'first/results.json', result)
    manifest = build_site(reports, site, 'https://github.com/neuroscales/brainhops-eval/actions/runs/123')
    assert not manifest['passed'] and manifest['complete']
    assert '1 error' in (site / 'index.html').read_text()
    assert 'Unsupported transform type' in (site / 'simpleitk-python/example/index.html').read_text()
    assert not list(site.rglob('*.nii.gz'))
    assert (site / 'simpleitk-python/results.json').exists()
    assert (site / 'site.json').exists()


def test_site_refuses_mixed_versions(tmp_path):
    reports = tmp_path / 'reports'
    _artifact(reports / 'a', 'simpleitk', 'one')
    _artifact(reports / 'b', 'ants', 'two')
    with pytest.raises(ValueError, match='mixed brainhops commits'):
        build_site(reports, tmp_path / 'site')


def test_site_without_reports_is_explicitly_incomplete(tmp_path):
    manifest = build_site(tmp_path / 'missing', tmp_path / 'site')
    assert not manifest['complete'] and not manifest['passed']
    assert 'No backend produced a report' in (tmp_path / 'site/index.html').read_text()
