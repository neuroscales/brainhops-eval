# Validation notes

The initial local evaluation used brainhops commit
`04d278618652ec3bda4b3ec46d4278734ced6bf7`, SimpleITK 2.5.2, and the ANTs
binaries from the digest-pinned 2.6.0 image. Full Python dependency versions
are recorded in each generated report; they are not inferred from image tags.

## Explicit Python geometry path

The SimpleITK suite covers known and estimated transforms serialized as TFM
and HDF5; native, flipped-handedness, downsampled, alternate-reference, integer
intensity, and label inputs; and known-transform PNG/NPY cases. The direct
Python path composes `pull.inverse() @ source.transformation` before reslicing,
so the test expresses the physical mapping without depending on the calling
convention of `Image.__call__`.

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
an interior maximum absolute error of about 578 intensity units. The same
fixture passed through explicit Python geometry composition with maximum
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

Local validation exercises the Python tooling and actual ANTs binaries; it
does not substitute for building and running both SIF definitions on the
GitHub-hosted runner. The Actions workflow performs those builds, records
SIF checksums and package inventories, and uploads diagnostic results even
when comparisons fail. ARM runners are not supported by the initial digest
pins.
