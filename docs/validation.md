# Validation notes

Evaluation applies native pull transforms directly to the objects returned by
`brainhops.io.images.load`:

```python
source = io.images.load(source_path)
reference = io.images.load(reference_path)
pull = io.load(transform_path)
resliced = source(pull).reslice(reference, ...)
```

No replacement images, input dtype casts, array transposes, or geometry adapters are
used. Earlier green evaluation runs reconstructed images and cast data to
float32; their agreement results do not establish agreement for loaded images.
Those workarounds have been removed.

## Direct-loaded results

Against brainhops commit `04d278618652ec3bda4b3ec46d4278734ced6bf7`:

- SimpleITK synthetic fixtures, comparing in output dtype: 21 pass and 4 fail.
  The unsupported NPY image case has been removed.
- ANTs synthetic fixtures, comparing in output dtype: 12 pass and 18 fail.
- Integer NIfTI linear interpolation computes in float, then rounds/clips
  and casts back to the input dtype before returning. That quantized output
  differs from the float32 native reference by up to approximately 0.5 units.
  Those raw differences are now diagnostic, rather than the acceptance test.
- Float32 downsampled cases and nearest-neighbor label cases pass.
- PNG passes without a geometry adapter, but brainhops warns that some axes
  were matched by position because names, units, or orientations did not
  distinguish them.
- NPY has no implemented image reader in the tested commit, so it is excluded
  from active image compatibility cases. NPY serialization for expected arrays
  and masks does not exercise brainhops image loading.

The reference is now converted to the decoded brainhops output dtype before
acceptance comparison. Integer conversion rounds half away from zero and
clips to the dtype range; integer comparison is exact. Float references are
cast to output precision and use the existing float tolerances. Raw-reference
metrics remain in each report, and no loaded image is modified.

Remaining integer discrepancies are one unit at a few interior voxels per
failing case. For example, the float32 reference stores 77.5 (which rounds to
78), while brainhops produces 77. Such differences can arise when interpolation
or reference-storage precision puts values on opposite sides of a rounding
boundary. They are retained as failures, with exact mismatch counts, rather
than allowing a blanket one-unit tolerance. CI can therefore still fail.

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
conversion, not through poor interpolation precision. The converted reference
now matches these integer samples; the raw float discrepancy remains diagnostic.

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

## Additional native packages (2026-10-15)

Local native generation was exercised against brainhops commit
`04d278618652ec3bda4b3ec46d4278734ced6bf7`, using the direct loaded-image API.
Each added recipe generated 14 cases: known/registered affine × seven variants
(native, reflected, downsampled, oblique reference, uint8, int8, labels).
Every native output also passed an independent physical RAS pull calculation.
This validates native matrix direction, grid handling and image storage layout
separately from brainhops agreement.

| Native package | Independent native maximum absolute difference | brainhops passes / cases |
| --- | --- | --- |
| FSL 6.0.4 | 0.01465 (floating output) | 4 / 14 |
| NiftyReg 2.1.2 | 1.00002 (integer output truncation included) | 0 / 14 |
| elastix 5.0.1 | 0.000727 (floating output) | 10 / 14 |
| MRtrix3 3.0.3 | 0.001669 (floating output) | 0 / 14 |

FSL and elastix failures are integer mismatches of one unit. FSL had 1–44
interior mismatches in its failing cases. NiftyReg and MRtrix show much larger
mapping differences (hundreds of intensity units for the int16 phantom), even
though the loaded native RAS affine has the expected numeric matrix. These are
reported as failures, without replacing loaded images or relabelling systems.
The issue requires investigation in brainhops rather than an evaluator adapter.

MRtrix writes some output NIfTI files with different storage-axis order.
Evaluation undoes only the native output's exact permutation/flip and verifies
its resulting affine and shape against the requested reference grid. This is
lossless; it does not interpolate data or modify brainhops-loaded objects.

These are local native-runtime results, not claims that all four new SIF
builds or numerical CI jobs pass. CI builds and runs the separate definitions,
and always uploads quantitative results and shared-window montages.


## Boundary warnings and affine-reader investigation (2026-10-16)

Boundary-only discrepancies now have nonblocking warning status in JSON/HTML
and Actions summaries. Interior acceptance thresholds are unchanged. Boundary
values were already excluded from the earlier pass/fail calculation; sparse
integer differences inside the mask remain failures.

The NiftyReg/MRtrix root cause is now isolated: conversion of metadata-backed
reader objects to generic Affine loses their matrix, and separable factorisation
treats the missing matrix as identity. See the [investigation and minimal
reproducer](affine-reader-investigation.md), including a candidate upstream patch
validated in a separate worktree and the independent NiftyReg truncation issue.
The evaluator continues to test the unmodified selected brainhops version.
