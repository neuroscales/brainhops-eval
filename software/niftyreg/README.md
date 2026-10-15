# NiftyReg

Builds CPU-only NiftyReg **2.1.2** from the pinned release commit
`79a17622608fda35dcce9c65560c834009e8743c`. Runs `reg_aladin` affine registration
with three pyramid levels, ten iterations and one thread, and `reg_resample`
with linear or nearest interpolation and zero padding.

Its affine is a reference-world RAS mm → floating-world RAS mm pull map.
Matrices are loaded explicitly with `hint="niftyreg.aladin"`; a plain text
matrix otherwise has ambiguous format. Known and registered matrices are
reapplied across all seven shared image/grid variants, including signed int8.
Native integer outputs are retained, including NiftyReg's own quantisation.

```sh
python -m software.niftyreg.generate --inputs work/inputs --output work/niftyreg-fixtures
```

Requires native binaries on PATH and the shared numerical requirements.
Generation does not import brainhops. It records commands, version, landmark
errors and independently verifies native resampling against the physical pull.
Direct brainhops RAS-transform application currently shows substantial
numerical disagreement on these fixtures; reports retain these failures.
