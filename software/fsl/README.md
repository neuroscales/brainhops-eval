# FSL

Runs FLIRT affine registration (12 DOF, least squares, ±15° search), then
`flirt -applyxfm` with trilinear/nearest interpolation and floating output.
Known and estimated matrices are both exercised across all shared variants.

The runtime is FSL 6.0.4 (`6.0.4:ddd0a010`), from a pinned brainlife Docker
layer. The container streams and verifies that layer's SHA256 while extracting
FLIRT, FSL libraries and licence files. This avoids unpacking the upstream
atlas/data installation, which exceeds small CI disks. The download remains
about 7 GB; the resulting runtime is much smaller. `extract_runtime.py` records
its source and file list. FSL's licence is retained; consult it for permitted use.

FLIRT files map moving **scaled mm** to reference **scaled mm**, including an
x reflection when the voxel-to-world determinant is positive. The transform's
original registration images are retained in `transform_images`; brainhops
loads those images directly to interpret the matrix, even when reslicing a
downsampled or reflected moving image or using another reference grid.
FSL receives a matrix re-encoded for each application pair, preserving the same
physical mapping. No anatomical re-registration occurs for those variants.

```sh
python -m software.fsl.generate --inputs work/inputs --output work/fsl-fixtures
```

Requires FLIRT on PATH, FSLDIR and LD_LIBRARY_PATH set to its runtime, plus the
shared numerical requirements. Generation does not import brainhops. Commands,
version/build, landmark errors and an independent geometric resampling check
are saved. Numerical disagreement remains a failed brainhops comparison.
