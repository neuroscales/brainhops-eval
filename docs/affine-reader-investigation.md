# NiftyReg and MRtrix affine application failure

Investigated against brainhops `04d278618652ec3bda4b3ec46d4278734ced6bf7`.
The same faulty converter is present in current main
`be2b830d614f5d1420a030fd824734df152378ad`.

## Root cause

The registration is dropped during generic affine conversion and separable
factorisation. The file readers decode the correct physical RAS pull matrix;
this is not a RAS/LPS flip, transform-direction error or native grid mismatch.

1. `NiftyRegAffine` and `MrtrixLinearTransform` derive public `data`/`matrix`
   from their file metadata. Their inherited storage field `_data` is still
   `None` until a value is explicitly assigned.
2. `_convert_withlog` tests whether the source class **has** an inherited
   `_data` field using `stores(type(t), "_data")`. Both readers do, so the
   converter decides it can copy storage without transferring `t.matrix`.
3. `transform.to(Affine)` therefore has `matrix=None`, despite the loaded
   transform having a nonidentity matrix. In the transformation model,
   `None` means identity.
4. `compute.utils.affine_matrix` calls that conversion when analysing the
   sequence for factorisation. The registration is treated as identity and
   dropped. `source(transform).reslice(reference, ...)` effectively regrids
   the original image without the registration.

Source locations on current main:

- [The incorrect field-presence test](https://github.com/neuroscales/brainhops/blob/be2b830d614f5d1420a030fd824734df152378ad/src/brainhops/datamodel/_transformations/compute/converters.py#L114)
- [Affine conversion used by factorisation](https://github.com/neuroscales/brainhops/blob/be2b830d614f5d1420a030fd824734df152378ad/src/brainhops/datamodel/_transformations/compute/utils.py#L237)
- [Metadata-derived NiftyReg data](https://github.com/neuroscales/brainhops/blob/be2b830d614f5d1420a030fd824734df152378ad/src/brainhops/io/transformations/niftyreg/_affine.py#L110)

## Minimal reproduction

No native registration executable is needed:

```sh
python scripts/diagnose_affine_readers.py --output work/affine-diagnostic
```

The script writes floating NIfTI ramp images with anisotropic spacing and a
native text matrix that pulls one x voxel forward. It loads the files through
`io.images.load` and `io.load(hint=...)`, then calls
`source(transform).reslice(reference, ...)` directly. It never constructs a
replacement brainhops image or substitutes a transform in the application.
It checks an interior region only and records `diagnostic.json`.

Both readers produce the same evidence:

| Check | Unmodified brainhops | Candidate fix |
| --- | --- | --- |
| Loaded matrix x translation | 1.25 mm | 1.25 mm |
| Converted generic affine x translation | missing (`matrix=None`) | 1.25 mm |
| Interior maximum error on ramp | 100 | 0 |
| Output equals untransformed ramp interior | yes | no |

The script exits nonzero when the map is lost; it is a product diagnostic,
not a tooling test that assumes the current bug must persist.

## Candidate upstream correction

[The reviewable patch](patches/brainhops-derived-affine-conversion.patch)
transfers the public parameter view when converting away from the concrete
source class, rather than inferring readable data from a storage-field
presence check. It also adds two regression cases that apply the transform
to directly loaded NIfTI images **before** checking generic conversion.

This patch was tested in a separate brainhops worktree. The evaluator and
its production comparisons have no monkeypatch, image adapter, replacement
transform or version-specific workaround. The patch has not been installed
into the selected brainhops version or pushed to the brainhops repository.
The candidate passed 364 selected brainhops tests covering the two readers,
affine inverses, factorisation, separable resampling and format conversion;
this was not a run of the entire brainhops test suite.

On the existing 14-case native bundles, the candidate removes the large mapping
errors. MRtrix has 9 accepted cases (7 boundary warnings) and 5 sparse one-unit
interior mismatches. NiftyReg has 4 accepted cases and 10 integer disagreements;
its floating downsampled cases agree to less than 0.000702 intensity units.

## Separate NiftyReg integer quantisation difference

NiftyReg 2.1.2 preserves the floating input's datatype for `reg_resample` output.
Its `NiftiImage::clampData` saturates and uses `static_cast<RetT>(value)`, which
truncates toward zero for integer output. Brainhops rounds half away from zero.
Casting the already-truncated native output to the brainhops output dtype
cannot recover the fractional values that NiftyReg discarded.

For the known native-grid int16 case, an independent floating interpolation
check away from integer boundaries found **0 truncation mismatches among
85,007 interior samples**, versus **42,132 nearest-rounding mismatches**.
After the candidate mapping fix, this produces one-unit discrepancies across
many interior voxels. These are not boundary errors and remain strict failures.
Native outputs and loaded brainhops input dtypes are retained.

## Boundary reporting

Boundary-only threshold violations now produce case status `warning`, warning
text, boundary maximum/NRMSE metrics and integer mismatch counts. Warning cases
are accepted and return a successful evaluator exit code. An interior mismatch
still produces `fail`, even if the case also has boundary warnings.

Boundary values were already excluded from acceptance before this change.
For example, the prior FSL run's 10 failing cases had 1–44 interior integer
mismatches each; elastix had four failing cases with 1–4 interior mismatches.
The much larger boundary errors visible in montages did not cause those verdicts.
