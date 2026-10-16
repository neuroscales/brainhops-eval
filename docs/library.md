# Evaluation library

`brainhops_eval` is installable without brainhops. Native generators stay in
`software/<package>/`; only the evaluation stage imports the selected brainhops
version. Public functions have annotations and docstrings; CI enforces source
formatting, imports and documentation.

## Stages and contracts

- `fixtures.generate(output, source=None)` creates images, world-preserving grid
  variants, landmarks and checksums. Source selection, image construction,
  integer scaling, raster construction and manifests are separate helpers.
- `evaluate.evaluate(fixtures, output, brainhops_ref, brainhops_sha, interface)`
  verifies the immutable bundle, runs independent cases, and writes reports even
  when individual cases fail. It returns whether every interior comparison
  passes. An existing nonempty output directory is refused.
- `resampling.execute(...)` dispatches the public Python or CLI application.
  Python uses **the objects returned by `io.images.load`** and calls
  `source(pull).reslice(reference, degree=..., bound=...)`. It never reconstructs,
  casts, relabels or replaces an input image. Original registration images are
  separately loaded only when the transform format requires them.
- `comparison.assess(...)` compares decoded brainhops output against native
  values converted to that output dtype. Integer comparisons are exact after
  rounding/saturation of the reference; floating comparisons require both the
  maximum-error and normalised-RMSE limits. `comparison.conclude(record)` adds
  explicit diagnostic reasons and determines pass/warning/fail.
- `statistics` derives software statuses, failure categories and grouped counts
  from recorded outcomes without changing acceptance decisions.
- `report_sections` renders the statistical tables, navigation, numerical
  comparisons and inline montage gallery as independent documented helpers.
- `report.write_report(output, result)` writes a searchable offline overview,
  an individual page for every case, local styles/scripts and inline montages. Error
  summaries identify the stage; full tracebacks remain expandable.
- `site.build_site(reports, output, run_url)` assembles one evaluation run's
  artifacts into a static portal. It refuses mixed brainhops commits or
  duplicate backend/interface reports. No results produces an explicit
  incomplete page, never a successful empty evaluation.

`expected_on_reference_grid` can losslessly reorder **native reference storage**
axes and verifies exact grid agreement. It never resamples expected data or
changes a loaded brainhops object. NPY files hold expected arrays and masks;
they are not passed to brainhops as image-format tests.

## Report meanings

- **Pass:** interior and boundary limits are satisfied.
- **Warning:** the interior passes, but excluded boundary values disagree.
- **Fail:** interior numerical limits, exact integer equality, or axis checks
  fail. A case can fail NRMSE even when maximum absolute error passes; both
  observed values and both limits are shown.
- **Error:** a reader, application, output check or plotting stage raised an
  exception. The case page identifies that stage and preserves the exception.

A failure is an observed disagreement, not an automatic root-cause attribution
to brainhops. Registration accuracy, format capabilities, interpolation,
quantisation and image/field boundary conventions must be considered separately.
