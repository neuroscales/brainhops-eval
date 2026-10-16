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

The inputs are the shared generator's image variants, canonical mapping
parameters (`landmarks.json` and `raster-transform.json`), and provenance.
Each recipe serializes these known mappings into its native transform format.
Output
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
  `nifti` and `png`. NPY is used only for expected arrays and masks, not
  as an image input to brainhops.
- Optional `transform_hint` selects the native reader explicitly. Optional
  `transform_images` maps reader option names to **original registration image**
  paths; the evaluator loads these via `io.images.load`, separately from the
  actual application pair. Both Python and CLI honor these options.
- Optional `display_window: [low, high]` fixes one window across all anatomy
  panels and packages. Difference panels retain a separately labelled scale.
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

The FSL, NiftyReg, elastix and MRtrix recipes use `software/_shared/affine.py`
for bundle writing and independent world-coordinate validation. Each recipe
owns native registration, transform encoding and resampling. The independent
SciPy check validates conventions; native software produces the expected image.
Native outputs may differ in storage axes only: the evaluator can undo an exact
permutation/flip, but rejects any change to the requested physical sampling grid.

## Nonlinear and composite coverage

Each recipe appends nonlinear cases by default; the installed `brainhops_eval`
package only consumes the resulting bundle. No native generator imports brainhops.

| Software | Native transform representations attempted (build omissions recorded below) |
| --- | --- |
| SimpleITK / ITK | 2D PNG and 3D physical images; identity, translation, scale/log scale, Euler, similarity, affine/matrix-offset, versor variants, quaternion rigid and composed scale/skew; B-spline orders 0–3; dense and inverse displacement; mixed affine/B-spline/field composites in both orders; TFM, HDF5, MATLAB and vector NIfTI where encodable; estimated B-spline and affine+B-spline |
| ANTs | Native-reader-supported ITK representations above, including 2D PNG; estimated SyN forward/inverse NIfTI warps and native affine+SyN HDF5 composites in both orders |
| FSL | FNIRT quadratic/cubic coefficients with embedded affine; relative displacement and absolute coordinate fields; coefficient-to-dense conversions; inverse field and materialised warp+affine composition |
| NiftyReg | All seven `NREG_TRANS_TYPE` values: deformation, displacement, cubic/linear control grids, dense positional/displacement velocities and spline velocity; native integration/conversion; estimated cubic grid and affine+field composition |
| elastix | Translation, Euler (both rotation orders), similarity, affine, affine-log, affine-DTI; ordinary/recursive B-spline orders 1–3; Compose/Add chains, nested relative parameter references and estimated affine+B-spline chain |
| MRtrix | Coordinates/displacements and affine+warp composition in MIF, compressed MIF and detached MIH; estimated forward/inverse deformation; full 5D registration warps in MIF/MIH, both source images and halfway/full mapping modes |

`coverage.json` lists every generated representation and its application cases,
plus explicit unavailable capabilities and native reader/converter errors.
“Tested” means a native reference exists, not that brainhops passes it. Unsupported
brainhops inputs that the native tool can apply remain visible evaluation errors.
Known gaps include ITK MATLAB composites, FNIRT DCT evaluation, ANTs time-varying
velocity/MINC, and NiftyReg velocity affine extensions and 2D fields. This matrix
covers the public reader families; it is not a claim to enumerate every transform
class available in every upstream ITK build.

Known maps are spatially varying and asymmetric; mixed composites do not commute.
Estimated nonlinear maps come from the actual registration programs. Each native
representation is reapplied to world-preserving grid/orientation/dtype variants.
Native nearest-resampled, eroded source support defines the comparison interior;
field-domain borders are also excluded. Expected images always come from the
native application tool. Original loaded brainhops images are used unchanged.
Independent RAS checks validate known NiftyReg fields and FSL scaled-frame mapping;
ITK serialization checks preserve physical point mappings and spline order.
These checks validate representation/application agreement, not registration
accuracy against a known nonlinear anatomical ground truth.

Reports include coverage, quantitative comparisons, and lazy-loaded montages;
all existing artifact retention and selected brainhops ref options apply to the
expanded suites. A genuine interior or reader failure still makes evaluation fail.
