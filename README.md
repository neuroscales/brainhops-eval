# brainhops-eval

Generate registration and resampling fixtures with native packages, then
compare a chosen version of [brainhops](https://github.com/neuroscales/brainhops)
against those results. Reports include slices, checkerboards, difference
images, metrics, image geometry, and version provenance.

Fixture generation never imports brainhops. Registration quality and transform
application agreement are separate results: an imperfect registration can
still be applied correctly by both resamplers.

## Run in GitHub Actions

After the workflows are merged into the default branch, open **Actions →
Evaluate brainhops → Run workflow**. Set:

| Input | Meaning |
| --- | --- |
| `brainhops_ref` | Commit SHA, tag, or branch in `neuroscales/brainhops` |
| `packages` | Software folder names (comma-separated), or `all` |
| `dataset` | `phantom` or the pinned `nibabel-anatomical` example |
| `interface` | `python` for the public image application API; `cli` for documented CLI behavior |
| `fixtures_run_id` | Optional previous run ID whose native fixtures should be reused |

The ref is resolved **once** to a full commit SHA before installation. That SHA
is used for checkout, artifact naming, and report provenance. Ref values are
passed as action inputs or quoted environment values, never interpolated into
shell code. The workflow has read-only permissions and does not publish a site
or release. Installing a selected ref executes that repository's build code.

Download the `report-...` artifact and open `index.html`. Failed comparisons also
upload their report. `results.json` records the resolved brainhops commit,
installed dependencies, fixture-manifest checksum, and per-case outcomes.
Native fixture bundles and container provenance are separate artifacts.

**Generate native fixtures** can also run independently. To test several
brainhops versions against exactly the same results, generate fixtures once,
then pass that run's ID to subsequent evaluation runs. Select package(s) for
which that run contains artifacts. `dataset` only applies to generation; a
reused fixture records its actual source. Artifacts expire after 90 days;
archive approved bundles externally for durable regression fixtures.

Both workflows can be called from another workflow. Cross-repository calls
must use this repository's qualified workflow path at a pinned ref:

```yaml
jobs:
  interoperability:
    permissions:
      contents: read
      actions: read
    uses: neuroscales/brainhops-eval/.github/workflows/evaluate.yml@main
    with:
      evaluator_ref: main # pin this to the same ref as the uses: line
      brainhops_ref: main  # or a tag/full commit SHA
      packages: simpleitk
      interface: python
```

For cross-repository calls, pin `evaluator_ref` to the same ref as the `uses:`
line. The jobs explicitly check out this evaluation repository. Generated
artifacts belong to the calling workflow's repository, so `fixtures_run_id`
must refer to a run in that repository. Internal calls and manual runs check out
the evaluation workflow's own commit automatically.

Pull-request CI runs the tooling tests and the complete container-based Python
evaluation against brainhops `main`, using both reference packages.

## Repository layout

```text
src/brainhops_eval/        # Shared datasets, augmentations, evaluation, reports
software/
  simpleitk/
    container.def
    generate.py
    requirements.txt
    README.md
  ants/
    container.def
    generate.py
    requirements.txt
    README.md
  _shared/itk.py          # Optional native ITK utilities, outside the package
scripts/select_software.py
```

Native registration, transform application, software dependencies, and container
entrypoints belong in each software folder. They are not installed as part of
`brainhops-eval`. The two current recipes reuse ITK bundle-writing utilities
under `software/_shared`; a new recipe need not use those utilities or Python.
Shared inputs describe known mappings as JSON; each recipe writes the native
transform files it needs.
The installed package has no software-specific generator command or dependency
extra. Its CLI only fetches data, generates shared inputs, and evaluates bundles.

See [the software contract](software/README.md) to add a recipe. Actions discovers
folders containing `container.def`; selecting `all` includes new folders without
changing a Python registry or a hard-coded workflow matrix.

## Run locally

Python 3.11+ is required. The selected brainhops version is installed separately:

```sh
python -m venv .venv
. .venv/bin/activate
pip install -e '.[test]' -r software/simpleitk/requirements.txt
pip install 'brainhops[nifti,pillow,itk] @ git+https://github.com/neuroscales/brainhops.git@YOUR_REF'

brainhops-eval generate --output work/inputs
python -m software.simpleitk.generate --inputs work/inputs --output work/fixtures
brainhops-eval evaluate --fixtures work/fixtures --output work/report \
  --brainhops-ref YOUR_REF --brainhops-sha RESOLVED_SHA
pytest -q
```

Use empty output directories; stale outputs are rejected. Local ref/SHA flags
are provenance supplied by the caller; GitHub Actions resolves them itself.

For real anatomy:

```sh
source_path=$(brainhops-eval fetch nibabel-anatomical)
brainhops-eval generate --source "$source_path" --output work/anatomical-inputs
```

See [dataset instructions](datasets/README.md) for OpenNeuro and other sources.

## Containers

Apptainer and SingularityCE definition files live with their generators in
`software/<name>/container.def`. Build from
the repository root so `%files` can copy the tooling:

```sh
sudo apptainer build work/simpleitk.sif software/simpleitk/container.def
apptainer run --cleanenv --containall --pwd /work \
  --bind "$PWD/work:/work" work/simpleitk.sif \
  --inputs /work/inputs --output /work/fixtures \
  --container-image /work/simpleitk.sif
```

Use `software/ants/container.def` for ANTs; its runscript selects its generator.
For a local run with ANTs binaries on PATH, use `python -m software.ants.generate`
with the same input/output flags. Both definitions pin
linux/amd64 base manifests by digest. Python numerical dependencies and
SimpleITK are pinned; build tools, transitive dependencies, and ANTs runtime
Debian packages are not fully locked. SIF bytes and the full installed package
list are recorded, so cached SIFs identify the actual generating environment.
Bitwise identical SIF rebuilds are not promised. CI caches SIFs by definitions,
tooling, and requirements. Seeds and thread settings are explicit.

## Initial coverage

| Reference package | Registration | Native application | Transform files |
| --- | --- | --- | --- |
| SimpleITK 2.5.2 | Rigid, exported as affine | SimpleITK resampler | ITK `.tfm`, `.h5` |
| ANTs 2.6.0 | Rigid | `antsApplyTransforms` | Native `.mat`, converted `.tfm`, `.h5` |

Each package applies a known affine and its estimated registration across:

- Different fixed/moving shapes, RAS/SLP layouts, anisotropic spacing, and
  nonzero origins; the moving grid is also oblique. A flipped moving grid
  explicitly exercises opposite handedness.
- A downsampled moving image and an oblique reference grid, preserving their
  anatomical coordinate frame.
- `int16`, `uint8`, and `float32` input files; nearest-neighbor label maps.
- Transform serialization round trips, independently checked on physical points.

The known affine includes rotation, translation, nonuniform scaling, and shear.
The estimated registration is rigid, so its anatomical fit is deliberately
imperfect; interoperability is checked against its actual estimated mapping.

SimpleITK additionally probes native PNG reader defaults with asymmetric,
non-square images. NPY is not an active image-format case because brainhops has
no NPY image reader. `.npy` files in bundles hold expected arrays and masks;
they are read by the evaluator, not passed to brainhops as images.

Evaluation loads sources and references with `io.images.load` and transforms
with `io.load`, then applies the transform directly to the returned image.
It does not reconstruct images, cast their data, transpose their arrays, or
attach replacement geometry. Raster axis checks compare the loaded shape,
pixel order, and numeric voxel-to-model map against the package probes. Axis
metadata and bridge warnings are recorded in JSON and HTML.

## Comparison semantics

Native ITK transforms are pull maps from fixed LPS physical space to moving LPS
physical space. NIfTI grids use RAS. The Python path uses the public API:

```text
source(native_pull).reslice(reference, ...)
```

The image call accepts the pull map and handles geometry composition before
reslicing onto the reference grid. The object returned by `io.images.load` is used
unchanged. Native reference outputs compute in float32; brainhops chooses its
output dtype through its normal API. In the tested commit, integer inputs are promoted to float during separable
resampling, then rounded/clipped and cast back to their original dtype before
return. Comparison with our float32 references can therefore fail due to output
quantization, not interpolation arithmetic. Reports record the in-memory and
reference output dtypes. We do not cast loaded inputs or relax tolerances.

Interior agreement requires maximum absolute error ≤ 0.02 and normalized RMSE
≤ 2e-5. Labels require exact values within 1e-5 and no new labels. A native
coverage mask excludes the source interpolation edge; boundary errors are
reported separately. Less than 5% interior coverage, non-finite data, wrong
output grids, and corrupted fixtures fail validation. Overlays use shared
intensity scaling; difference panels show their own maximum. Reference slices
are displayed in voxel axes, not falsely labelled as anatomical planes.

The optional CLI path passes `transform|inv`, following the current CLI's
documented push convention, and retains native input dtypes. It is a separate
contract test and may expose CLI direction or integer-quantization differences.
PNG uses direct application to `io.images.load` results in either mode;
each result records the interface it actually exercised.
No version-specific inversion is silently substituted. See
[validation notes](docs/validation.md) for observed behavior.

## Extending the suite

Next additions should include FSL and NiftyReg recipes, nonlinear fields and
their domains, chained transforms, explicit image-format conversions, qform/
sform precedence and scaling, and JPEG compression cases. A software recipe
must retain its original registration inputs, native transforms, commands,
version and defaults; generate native expected outputs; and declare transform
direction and coordinate systems. Conversions tied to the original grids must
retain those grids even when application inputs are regridded.

This initial repository provides two package containers and one working
generation/application/comparison path per package; it is not a complete
matrix of every format supported by brainhops.
