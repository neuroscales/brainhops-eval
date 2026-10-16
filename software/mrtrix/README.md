# MRtrix3

Uses Debian bookworm's pinned `mrtrix3=3.0.3-3+b1`. `mrregister` estimates an
affine at scales 0.5 and 1 (50/30 iterations, one thread). `mrtransform -linear`
reapplies known and registered transforms to all shared image variants.
Interpolation is explicitly linear/nearest; oversampling is set to 1 to compare
voxel-centre interpolants rather than an anti-aliasing filter. Output is float32.

Matrices map template scanner RAS mm to moving scanner RAS mm (MRtrix's reverse
convention), loaded with `hint="mrtrix.linear"`. Native NIfTI outputs sometimes
change storage-axis order. The evaluator losslessly permutes/flips only the
native reference output, verifying that its voxel-to-world grid then matches
the requested reference. Brainhops inputs are never reoriented or rebuilt.

```sh
python -m software.mrtrix.generate --inputs work/inputs --output work/mrtrix-fixtures
```

Requires native binaries on PATH and shared numerical requirements. Commands,
version, landmark errors and independent native world-coordinate checks are
saved. Direct RAS-transform application in brainhops currently disagrees with
native outputs; those cases fail visibly.

## Nonlinear cases

Also runs nonlinear registration and tests forward/inverse and full 5D warps, both from_image choices and halfway/full modes. Known coordinates, displacements and affine+warp composites are stored in .mif, .mif.gz and detached .mih. Halfway cases use the native halfway output grid.
