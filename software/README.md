# Native software recipes

Each software folder owns its container definition, native generation code,
software requirements, and usage notes. These folders are not part of the
installed `brainhops_eval` package. A recipe can use Python, shell, R, MATLAB,
or any runtime its container provides.

## Container interface

Actions discovers `software/<name>/container.def`. Names use lower-case letters,
numbers, hyphens, and underscores. The container's runscript must accept:

```sh
apptainer run --bind "$PWD/work:/work" software.sif \
  --inputs /work/inputs --output /work/fixtures \
  --container-image /work/software.sif
```

The inputs are the shared generator's image variants and provenance. Output
must be a new bundle directory. The recipe owns registration, native transform
application, package defaults/probes, conversion checks, and its runtime setup.
It must not import brainhops to produce reference results.

## Output contract

The current evaluator consumes:

- `inputs/`: original shared image variants and source metadata.
- `registration.json`: package/version, parameters, registration quality, and
  the generating SIF checksum.
- `cases.json`: schema version 1, backend name, transform convention, and cases
  with `id`, `kind`, `degree`, `moving`, `reference`, `transform`, `expected`,
  and `mask`. Paths are relative to the bundle. Current image kinds are
  `nifti`, `png`, and `npy`.
- Native transform files, expected resampled images, and boolean interior masks.
- `geometry-probes.json`: package input/reference geometry for raster cases;
  an empty object if no raster cases are generated.
- `manifest.json`: schema version 1 and SHA256 checksums of bundle files.

Native transforms must declare their direction and coordinate systems. The
current evaluator applies physical pull maps via `source(pull).reslice(...)`.
A different convention needs an explicit extension of that contract, not an
undocumented inversion. No evaluation-stage casting, reconstruction, or axis
correction should hide differences from the objects returned by image loading.

The existing recipes use `software/_shared/itk.py` for ITK serialization,
point checks, masks, and bundle bookkeeping. This helper stays outside the
installed package and contains no software-selection switch. Other software
can write the contract independently, using generic `brainhops_eval.files`
utilities if useful.

## Adding a recipe

1. Add a folder containing `container.def` and that software's generator and
   dependency files.
2. Implement its runscript and document its native commands/defaults.
3. Validate the output contract and include diagnostic cases.
4. Run Actions with `packages` set to the folder name or `all`.

There is no central list of software implementations. Per-software cache keys
include that folder and the common tooling, so changing another recipe does not
invalidate its container.
