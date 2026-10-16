"""Optional bundle utilities for native nonlinear recipes (never imports brainhops)."""

from pathlib import Path

import nibabel as nib
import numpy as np

from brainhops_eval.files import inventory, read_json, write_json


def world_grid(image):
    indices = np.indices(image.shape[:3], dtype=float).reshape(3, -1)
    return (image.affine[:3, :3] @ indices + image.affine[:3, 3, None]).T.reshape((*image.shape[:3], 3))


def smooth_displacement(points):
    """Non-affine, coupled, asymmetric physical RAS displacement in mm."""
    x, y, z = np.moveaxis(points, -1, 0)
    return np.stack([1.1 * np.sin(y / 13) * np.cos(z / 17),
                     .8 * np.sin((x + z) / 19),
                     .6 * np.cos(x / 11) * np.sin(y / 16)], axis=-1)


def aligned(path, reference):
    image, ref = nib.load(path), nib.load(reference)
    orientation = nib.orientations.ornt_transform(nib.orientations.io_orientation(image.affine),
                                                nib.orientations.io_orientation(ref.affine))
    image = image.as_reoriented(orientation)
    if image.shape != ref.shape or not np.allclose(image.affine, ref.affine, atol=1e-4, rtol=1e-6):
        raise ValueError(f"Native output is not on the reference grid: {path}")
    return image.get_fdata()


def append_cases(output, entries, apply_image, *, unavailable=()):
    """Apply every native representation to every shared world-preserving variant.

    `apply_image(entry, source, reference, degree, output, log)` is owned by the
    software folder. Interior masks use that same native transform application
    on an eroded source support image, with nearest interpolation.
    """
    output = Path(output)
    manifest = read_json(output / 'cases.json')
    variants = read_json(output / 'inputs/inputs.json')['variants']
    coverage = read_json(output / 'coverage.json') if (output / 'coverage.json').exists() else {
        'schema_version': 1, 'tested': [], 'unavailable': []}
    coverage['unavailable'].extend(unavailable)
    folder = output / 'nonlinear'
    folder.mkdir(exist_ok=True)
    for entry in entries:
        name = entry['id']
        transform = Path(entry['transform'])
        if not transform.is_absolute():
            transform = output / transform
        row = {key: entry[key] for key in ('id', 'family', 'representation', 'origin') if key in entry}
        row['transform'] = str(transform.relative_to(output))
        row['cases'] = []
        for variant in entry.get('variants', variants):
            case = dict(variant, id=name + '-' + variant['id'], kind='nifti',
                        moving='inputs/' + variant['moving'], reference='inputs/' + variant['reference'],
                        transform=str(transform.relative_to(output)), transform_family=entry['family'],
                        transform_representation=entry['representation'], transform_origin=entry['origin'])
            if entry.get('reference'):
                case['reference'] = entry['reference']
            for key in ('transform_hint', 'transform_images', 'transform_options'):
                if key in entry:
                    case[key] = entry[key]
            case_dir = output / 'cases' / case['id']
            case_dir.mkdir()
            source, reference = output / case['moving'], output / case['reference']
            expected = case_dir / 'expected.nii.gz'
            apply_image(entry, source, reference, case['degree'], expected, output / 'commands.log')
            if not np.isfinite(aligned(expected, reference)).all():
                raise ValueError(f'Native output contains nonfinite values: {expected}')
            image = nib.load(source)
            support = np.zeros(image.shape, dtype=np.float32)
            support[tuple(slice(2, -2) for _ in image.shape)] = 1
            support_path = case_dir / 'source-interior.nii.gz'
            nib.save(nib.Nifti1Image(support, image.affine), support_path)
            mask_path = case_dir / 'native-interior.nii.gz'
            apply_image(entry, support_path, reference, 0, mask_path, output / 'commands.log')
            mask = aligned(mask_path, reference) > .999
            if entry.get('domain'):
                domain = nib.load(output / entry['domain'])
                ref = nib.load(reference)
                pull = np.linalg.inv(domain.affine) @ ref.affine
                points = np.indices(ref.shape, dtype=float).reshape(3, -1)
                points = pull[:3, :3] @ points + pull[:3, 3, None]
                inside = np.all((points >= 2) & (points <= np.array(domain.shape[:3])[:, None] - 3), axis=0)
                mask &= inside.reshape(ref.shape)
            if mask.mean() < .05:
                raise ValueError(f'Insufficient native interior overlap: {case["id"]}: {mask.mean()}')
            np.save(case_dir / 'interior.npy', mask)
            case.update(expected=str(expected.relative_to(output)),
                        mask=str((case_dir / 'interior.npy').relative_to(output)),
                        mask_policy='native nearest-resampled source support eroded by two voxels; field domain eroded by two voxels')
            manifest['cases'].append(case)
            row['cases'].append(case['id'])
        coverage['tested'].append(row)
    write_json(output / 'cases.json', manifest)
    write_json(output / 'coverage.json', coverage)
    write_json(output / 'manifest.json', {'schema_version': 1, 'files': inventory(output)})
    return output
