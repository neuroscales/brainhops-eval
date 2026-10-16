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
    actual[1, 1] = 2
    record = _case(actual, np.zeros((4, 4)), np.ones((4, 4), bool))
    record['warnings'] = ['<script>alert("unsafe")</script>']
    assert record['status'] == 'fail'
    assert '1 of 16 interior voxels differ' in record['summary']
    write_report(tmp_path, _result(record))
    index = (tmp_path / 'index.html').read_text()
    detail = (tmp_path / 'example/index.html').read_text()
    assert 'Why this result?' in index and 'differences up to 1 unit only warn' in index
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


def test_integer_warning_is_reported_without_a_boundary_or_failure_label(tmp_path):
    """The portal distinguishes interior quantization warnings from boundary errors."""
    from brainhops_eval.statistics import issue_counts, software_statistics
    record = _case(np.ones((2, 2), np.int16), np.zeros((2, 2)), np.ones((2, 2), bool))
    result = _result(record)
    assert record['status'] == 'warning' and result['passed']
    assert issue_counts([record]) == {'integer-quantization': 1}
    assert software_statistics([dict(result, _report_path='simpleitk-python')])[0]['failed_families'] == {}
    write_report(tmp_path, result)
    detail = (tmp_path / 'example/index.html').read_text()
    assert 'differences up to 1 unit only warn' in detail
    assert 'Informational' in detail and 'exact int16 equality' not in detail


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
    context = root.parent / 'evaluation-context.json'
    if not context.exists():
        write_json(context, dict(brainhops_sha=sha, packages=[backend], interface='python'))
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


def test_site_marks_missing_requested_backend_incomplete(tmp_path):
    reports = tmp_path / 'reports'
    _artifact(reports / 'first')
    write_json(reports / 'evaluation-context.json',
               dict(brainhops_sha='commit-123', packages=['simpleitk', 'ants'], interface='python'))
    manifest = build_site(reports, tmp_path / 'site')
    assert not manifest['complete'] and not manifest['passed']
    assert manifest['missing_reports'] == ['ants-python']
    assert 'Missing reports: ants-python' in (tmp_path / 'site/index.html').read_text()


def test_site_legacy_run_does_not_claim_known_completeness(tmp_path):
    reports = tmp_path / 'reports'
    _artifact(reports / 'first')
    (reports / 'evaluation-context.json').unlink()
    manifest = build_site(reports, tmp_path / 'site')
    assert manifest['complete'] is None and not manifest['passed']
    assert 'completeness cannot be verified' in (tmp_path / 'site/index.html').read_text()


def test_report_refuses_case_path_traversal(tmp_path):
    case = _case(np.zeros((4, 4)), np.zeros((4, 4)), np.ones((4, 4), bool))
    case['id'] = '../outside'
    with pytest.raises(ValueError, match='escapes fixture directory'):
        write_report(tmp_path, _result(case))


def test_software_overview_keeps_warning_status_and_names_failed_tests(tmp_path):
    from brainhops_eval.statistics import software_statistics
    warning = _case(np.array([[5., 0], [0, 0]]), np.zeros((2, 2)),
                    np.array([[False, True], [True, True]]))
    warning['transform_family'] = 'affine'
    failed = _case(np.full((2, 2), 2, np.int16), np.zeros((2, 2)), np.ones((2, 2), bool))
    failed['transform_family'] = 'B-spline'
    reports = [dict(_result(warning, 'ants'), _report_path='ants-python'),
               dict(_result(failed, 'elastix'), _report_path='elastix-python')]
    rows = {row['backend']: row for row in software_statistics(reports)}
    assert rows['ants']['status'] == 'warning'
    assert rows['ants']['counts'] == {'pass': 0, 'warning': 1, 'fail': 0, 'error': 0}
    assert rows['elastix']['failed_families'] == {'B-spline': 1}
    assert rows['elastix']['failure_reasons'] == {'integer-mismatch': 1}


def test_portal_has_software_navigation_statistics_and_inline_montages(tmp_path):
    from PIL import Image
    reports, site = tmp_path / 'reports', tmp_path / 'site'
    result = _artifact(reports / 'native')
    case = result['cases'][0]
    case.update(preview='example/comparison.png', transform_family='dense-displacement', degree=1,
                image_kind='nifti', moving='source.nii.gz')
    Image.new('RGB', (20, 20)).save(reports / 'native/example/comparison.png')
    write_json(reports / 'native/results.json', result)
    build_site(reports, site)
    overview = (site / 'index.html').read_text()
    software = (site / 'simpleitk-python/index.html').read_text()
    detail = (site / 'simpleitk-python/example/index.html').read_text()
    assert 'Results by software' in overview and 'Which tests fail?' in overview
    assert 'Software results' in overview and 'SimpleITK' in overview
    assert 'Transform family' in software and 'Output dtype' in software
    assert 'dense-displacement' in software and 'Image interpolation' in software
    assert 'Interior NRMSE' in software and 'Integer mismatches' in software
    assert 'Qualitative comparisons' in software
    assert 'src="./example/comparison.png"' in software
    assert 'aria-current="page"' in software
    assert '../../simpleitk-python/index.html' in detail


def test_legacy_failures_are_classified_from_observed_metrics():
    from brainhops_eval.statistics import issue_counts
    case = _case(np.full((2, 2), 2, np.int16), np.zeros((2, 2)), np.ones((2, 2), bool))
    case.pop('diagnostics')
    assert issue_counts([case]) == {'integer-mismatch': 1}
    case.update(status='error', error='Reader failed')
    assert issue_counts([case]) == {'execution-error': 1}


def test_one_case_is_counted_once_per_issue_not_per_axis_check():
    from brainhops_eval.statistics import issue_counts
    case = _case(np.zeros((2, 2)), np.zeros((2, 2)), np.ones((2, 2), bool))
    case['axis_interpretation'] = {'moving': {'checks': {'first': False, 'second': False}}}
    conclude(case)
    assert issue_counts([case]) == {'axis-interpretation': 1}
