"""Native edge conventions remain visible instead of being patched into images."""
import numpy as np

from brainhops_eval.boundaries import policy_for, reslice_options
from brainhops_eval.files import read_json
from brainhops_eval.report import _boundary_probe
from software._shared.boundaries import _predictions


def test_half_voxel_clamp_and_grid_padding_are_distinct():
    ramp = np.ones((4, 4, 4), np.float32) * 10
    coords = np.array([[-.75, -.25, 0, 3.25, 3.75], [1] * 5, [1] * 5])
    models = _predictions(ramp, coords, 1)
    np.testing.assert_allclose(models['grid-constant'], [2.5, 7.5, 10, 7.5, 2.5])
    np.testing.assert_allclose(models['half-voxel-clamp'], [0, 10, 10, 10, 0])


def test_native_simpleitk_probe_records_nonrepresentable_edge_rule(fixtures):
    probe = read_json(fixtures / 'boundary-probes.json')
    linear = next(item for item in probe['interpolation'] if item['degree'] == 1)
    assert 'half-voxel-clamp' in linear['matching_models']
    assert linear['model_errors']['grid-constant']['max_abs'] > 0
    assert len(linear['native_values']) == len(probe['sample_x_voxels'])
    rendered = _boundary_probe({'boundary_probes': probe})
    assert '<svg' in rendered and 'Dashed blue' in rendered
    assert 'Clamp within the half-voxel extent' in rendered


def test_fsl_sampler_policies_are_not_conflated():
    affine = policy_for('fsl', {'transform_hint': 'flirt'})
    warp = policy_for('fsl', {'transform_hint': 'fnirt'})
    assert 'estimated background' in affine['native_rule']
    assert 'applywarp' in warp['native_rule']
    assert affine['brainhops_bound'] == 'constant'
    assert warp['brainhops_bound'] == 'constant'
    assert affine['brainhops_clip'] is warp['brainhops_clip'] is None



def test_fixed_clipping_policies_and_old_version_fallback():
    for backend in ['simpleitk', 'ants', 'mrtrix', 'elastix']:
        linear = policy_for(backend, {'degree': 1}, supports_clip=True)
        assert reslice_options(linear) == {'bound': 'mirror' if backend == 'elastix' else 'nearest', 'clip': 0.5}
        legacy = policy_for(backend, {'degree': 1}, supports_clip=False)
        assert reslice_options(legacy) == {'bound': 'constant'}
        assert legacy['requested']['clip'] == 0.5 and legacy['capability_fallback']
        nearest = policy_for(backend, {'degree': 0}, supports_clip=True)
        assert reslice_options(nearest) == {'bound': 'constant'}
    assert reslice_options(policy_for('niftyreg', {'degree': 1}, supports_clip=True)) == {'bound': 'constant'}


def test_boundary_probes_use_original_readers_and_upstream_reslice(fixtures, monkeypatch):
    import brainhops.io as bio
    from brainhops.backends import backend
    from brainhops.datamodel.images import SingleScaleImage
    from brainhops_eval.boundary_probes import evaluate_boundary_probes

    original_load, original_reslice = bio.images.load, SingleScaleImage.reslice
    loaded, applied = set(), []

    def track_load(*args, **kwargs):
        image = original_load(*args, **kwargs)
        loaded.add(id(image))
        return image

    def track_reslice(image, reference, **options):
        assert id(image) in loaded and id(reference) in loaded
        applied.append(options)
        return original_reslice(image, reference, **options)

    monkeypatch.setattr(bio.images, 'load', track_load)
    monkeypatch.setattr(SingleScaleImage, 'reslice', track_reslice)
    native = read_json(fixtures / 'boundary-probes.json')
    context = dict(backend='simpleitk', boundary_probes=native, reslice_capabilities={'clip': True})
    with backend('numpy'):
        measured = evaluate_boundary_probes(bio, fixtures, context)
    assert applied == [{'degree': 0, 'bound': 'constant'}, {'degree': 1, 'bound': 'nearest', 'clip': 0.5}]
    assert all(item['brainhops']['status'] == 'measured' for item in measured['interpolation'])
    assert measured['interpolation'][0]['brainhops']['max_abs'] == 0
    linear = measured['interpolation'][1]['brainhops']
    assert linear['mismatch_count'] == 1  # Native upper endpoint is excluded; upstream clip is closed.
    assert 'brainhops' not in native['interpolation'][0]
    rendered = _boundary_probe({'boundary_probes': measured})
    assert 'actual upstream brainhops reslice samples' in rendered
    assert 'Measured brainhops max error' in rendered
