# Validation notes

Evaluation applies native pull transforms directly to the objects returned by
`brainhops.io.images.load`:

```python
source = io.images.load(source_path)
reference = io.images.load(reference_path)
pull = io.load(transform_path)
resliced = source(pull).reslice(reference, ...)
```

No replacement images, dtype casts, array transposes, or geometry adapters are
used. Earlier green evaluation runs reconstructed images and cast data to
float32; their agreement results do not establish agreement for loaded images.
Those workarounds have been removed.

## Direct-loaded results

Against brainhops commit `04d278618652ec3bda4b3ec46d4278734ced6bf7`:

- SimpleITK synthetic fixtures: 9 pass and 16 fail numerical comparison.
  The unsupported NPY image case has been removed.
- ANTs synthetic fixtures: 10 pass and 20 fail numerical comparison.
- Integer NIfTI linear interpolation computes in float, then rounds/clips
  and casts back to the input dtype before returning. That quantized output
  differs from the float32 native reference by up to approximately 0.5 units.
  This exceeds the unchanged maximum-error and normalized-RMSE thresholds.
- Float32 downsampled cases and nearest-neighbor label cases pass.
- PNG passes without a geometry adapter, but brainhops warns that some axes
  were matched by position because names, units, or orientations did not
  distinguish them.
- NPY has no implemented image reader in the tested commit, so it is excluded
  from active image compatibility cases. NPY serialization for expected arrays
  and masks does not exercise brainhops image loading.

The native reference computes in float32. These results expose an output-dtype
policy difference; they do not by themselves establish that integer rounding
is a brainhops bug. The evaluator neither loosens thresholds nor casts inputs
to hide the difference. Evaluation CI is expected to fail until the tested
library behavior or an explicitly agreed comparison policy changes.

The tooling tests independently check native resampling against known RAS
mappings, landmark positions, fixture integrity, dataset checksums, and report
creation. They also verify that image application uses the same object that
`io.images.load` returned. Reporting tests distinguish evaluator correctness from
whether the selected brainhops version agrees with native references.

## Where integer rounding occurs

In `datamodel/_transformations/compute/separable.py`, the reslicer saves the
input dtype, promotes non-floating input with `data.astype(float)`, and performs
its separable steps. Before returning, it rounds integer results half away from
zero, clips to the original dtype range, and casts back. The general pull path
also allocates its output with the input dtype in `_core/bsplines.py`.

This happens before image saving. A direct loaded-image test on a ramp with
values 0, 3, 6, sampled half a voxel along x, gives:

| Loaded input dtype | In-memory result dtype | Result samples |
| --- | --- | --- |
| int16 | int16 | 2, 5 |
| float32 | float32 | 1.5, 4.5 |

Those are separate on-disk inputs, both loaded and resliced directly without
replacement brainhops objects. The fractional values are lost at output
conversion, not through poor interpolation precision. Current raw comparison
failures remain visible until an output-dtype comparison policy is agreed.

## Axis interpretation

Raster checks independently compare the package-probed size and grid mapping
with the loaded image, and compare its pixel order with the file storage order
interpreted by the native package. Checks can fail even when resampled values
match. The report retains both grid maps and the loaded axis names, units,
and orientations. The image is not relabelled or transformed to satisfy these
checks. Tests verify detection of swapped dimensions and flipped directions.
Bridge warnings are captured in the report; unknown anatomical orientation
is not silently treated as known.

## CLI convention

The tested CLI documentation describes transforms as push maps and instructs
users to invert native pull maps with `|inv`. The image application API accepts
pull maps. The documented CLI invocation produced a much larger mapping error
(approximately 612 intensity units in the known-transform native-grid case).
CLI evaluation follows its documented invocation and reports failures without
substituting a version-specific inversion. No brainhops code is changed here.

## Container execution

Both SIF definitions built and ran successfully in
[CI run 38783017651](https://github.com/neuroscales/brainhops-eval/actions/runs/38783017651).
The numerical passes from that historical run used the removed image wrappers
and must not be cited as direct-loaded validation. The workflow records SIF
checksums and package inventories, and uploads reports when comparisons fail.
ARM runners are not supported by the initial digest pins.
