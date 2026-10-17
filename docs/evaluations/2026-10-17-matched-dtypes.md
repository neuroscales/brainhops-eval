# Matched integer and float32 applications

This follow-up to [run 38976888559](https://github.com/neuroscales/brainhops-eval/actions/runs/38976888559)
uses the same stored registrations, brainhops commit
`49e607d306b72d1a61516fbcfbcbfc485079abac`, FSL 6.0.4 and NiftyReg 2.1.2.
It isolates storage dtype from grid changes. Each float32 image contains the
exact same voxel values and geometry as its integer counterpart. Native
expected images and masks are regenerated using the original transformations.
Both native and brainhops outputs of the counterpart cases are float32.

The focused evaluation covers 26 FSL applications (quadratic and cubic
coefficients over all thirteen variants) and thirteen NiftyReg spline-velocity
applications. These are diagnostic subsets, not a new complete six-package run.

## Interior maximum absolute errors

| Transformation and grid | Integer dtype | Integer error | Float32 error |
| --- | --- | ---: | ---: |
| FSL quadratic coefficients, native | int16 | 1 | 0.001953 |
| FSL quadratic coefficients, oblique reference | int16 | 2 | 1.895203 |
| FSL cubic coefficients, native | int16 | 1 | 0.002197 |
| FSL cubic coefficients, oblique reference | int16 | 3 | 2.419250 |
| NiftyReg spline velocity, native | int16 | 1 | 0.175934 |
| NiftyReg spline velocity, oblique reference | int16 | 1 | 0.266449 |
| NiftyReg spline velocity, uint8 intensity range | uint8 | 1 | 0.047211 |
| NiftyReg spline velocity, int8 intensity range | int8 | 1 | 0.023788 |

FSL's oblique-reference failures therefore persist with floating-point input
and output. They reflect the native rasterization/rebasing path described in
[evaluation issue #6](https://github.com/neuroscales/brainhops-eval/issues/6),
rather than integer rounding alone. On the native grid, the float32 numerical
comparison passes; boundary differences can still produce warning status.

NiftyReg's integration-grid discrepancy also persists with floating-point data.
The int16 native and oblique cases only warn because one-unit integer
differences are tolerated. Their matched float32 cases fail the 0.02 absolute
tolerance. The previously reported downsampled float32 case still has error
0.106110, but it is no longer the sole floating-point observation.
The integration issue remains tracked in
[brainhops #513](https://github.com/neuroscales/brainhops/issues/513).

Nearest-neighbour label cases are also paired without changing their
interpolation degree. FSL labels match exactly in both dtypes. NiftyReg has a
one-label mismatch in both dtypes: the integer policy warns, while the floating
policy fails. Matching stored values does not imply matching status because
the two acceptance policies intentionally differ.

## Coverage and safeguards

The shared generator adds float32 counterparts for native int16, reflected,
oblique-reference, uint8, int8 and label variants. All six software recipes
consume these variants, including MRtrix's restricted midway cases. The
downsampled float32 variant remains separate. PNG has no floating-point storage
equivalent and remains an integer reader/axis test.

The report includes a table of matched statuses, output dtypes and interior
maximum errors. Tests verify unchanged values, affines, qforms, interpolation,
display ranges, transform files and native masks. Evaluation applies each
transformation to the native loaded image objects. It does not cast those
objects, reconstruct images, repair geometry or change comparison thresholds.
