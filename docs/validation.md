# Validation notes

The initial local evaluation used brainhops commit
`04d278618652ec3bda4b3ec46d4278734ced6bf7`, SimpleITK 2.5.2, and the ANTs
binaries from the digest-pinned 2.6.0 image. Full Python dependency versions
are recorded in each generated report; they are not inferred from image tags.

| Local check | Result |
| --- | --- |
| Tooling tests | 11 passed |
| SimpleITK synthetic comparisons | 26/26 passed; worst interior absolute error 0.000733 |
| ANTs synthetic comparisons | 30/30 passed; worst interior absolute error 0.00184 |
| Anatomical download-path comparisons | 22/22 passed; worst interior absolute error 0.000992 |
| GitHub workflow syntax and expressions | actionlint 1.7.7 passed |

The anatomical check predates the additional handedness case. The ANTs image
tag is `v2.6.0`; the binaries report `2.6.0.dev1-gcff4f8b`, which is recorded
verbatim in fixture provenance.

## Public Python image application API

The SimpleITK suite covers known and estimated transforms serialized as TFM
and HDF5; native, flipped-handedness, downsampled, alternate-reference, integer
intensity, and label inputs; and known-transform PNG/NPY cases. The direct
Python path calls `source(pull).reslice(reference, ...)`, exercising the public
image application API with the native pull map. The image call handles
composition with the source geometry.

Tests independently compare the native package's result with SciPy sampling
through the known RAS voxel-to-voxel map, check landmark positions, check
output geometry, reject changed fixture bytes, exercise failed-comparison
reports, and verify dataset checksums and cache repair.

## CLI direction discrepancy in the tested commit

At the commit above, the CLI documentation describes `--transform` as a push
mapping and says that a native pull transform should be inverted with `|inv`.
However, `SingleScaleImage.__call__` itself inverts its argument before
composing it with the input geometry. The documented invocation therefore
applies the opposite mapping in this version.

With the known-transform native-grid case, the documented CLI invocation had
an interior maximum absolute error of about 612 intensity units. The same
fixture passed through the public Python image application API with maximum
absolute error below 0.001. The float32 downsampled case also failed in CLI
mode, so integer output quantization does not explain the discrepancy.

Reproduce against that commit with:

```sh
brainhops-eval evaluate --fixtures work/fixtures --output work/cli-report \
  --interface cli --brainhops-ref 04d278618652ec3bda4b3ec46d4278734ced6bf7 \
  --brainhops-sha 04d278618652ec3bda4b3ec46d4278734ced6bf7
```

The CLI evaluation follows the documented contract and fails visibly. It does
not select a different inversion based on the tested version. CLI mode also
preserves input storage dtypes, so integer quantization differences may remain
after the direction contract is fixed. No brainhops code is modified here.

## Execution limits

Both SIF definitions were also built and run successfully on the GitHub-hosted
runner in [CI run 38783017651](https://github.com/neuroscales/brainhops-eval/actions/runs/38783017651).
The container generation and evaluation jobs passed for both packages. The
workflow records SIF checksums and package inventories, and uploads diagnostic
results even when comparisons fail. ARM runners are not supported by the
initial digest pins.
