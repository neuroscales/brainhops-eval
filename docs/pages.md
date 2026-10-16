# Published evaluation reports

In **Settings → Pages → Build and deployment → Source**, select **GitHub Actions**.
Generated reports are not committed to the main branch or to a results branch.

After this workflow is merged, `Publish evaluation reports` automatically runs
when a trusted **main-branch** `Evaluate brainhops` or `Test evaluation tooling`
run completes. It downloads all available `report-*` artifacts and deploys a
static portal using the official Pages artifact/deployment actions. Numerical
failures do not prevent publication. A run producing no reports is labelled
incomplete and links back to its Actions logs.

To publish an earlier run, dispatch **Publish evaluation reports** with its
numeric Actions run ID. Report artifacts must still exist. The portal refuses
mixed brainhops commits and duplicate backend/interface pairs.

The site shows the **latest published run**, with the exact brainhops SHA,
per-package counts, searchable failure reasons, case pages and montages. Older
runs and full resliced images remain in their 90-day Actions artifacts. The
public site contains HTML, PNG, CSS, JS and quantitative JSON; full NIfTI/NPY
outputs and logs remain in the artifacts. Deployments are serialised.

A local preview uses the same builder:

```sh
brainhops-eval site --reports work/downloaded-reports --output work/site \
  --run-url https://github.com/neuroscales/brainhops-eval/actions/runs/RUN_ID
python -m http.server --directory work/site 8000
```

The report HTML and filters also work offline. Each result retains machine-readable
`results.json`; publication does not turn failed comparisons into passes.


## Reading the portal

The global overview has one row per software: overall success/warning/failure,
all four case counts, failing transform families and the checks that failed.
Warnings remain warnings even if every blocking comparison passes. Missing
reports remain explicitly incomplete.

A persistent software menu opens each complete results page. Its sections show:

- Failure/warning types and affected transform families, counted by test.
- Statistical tables grouped by transform family, output dtype, image
  interpolation and image format, including worst observed interior errors.
- Every case's maximum error and NRMSE beside its own limits, integer mismatch
  count, nonblocking boundary error and explanation.
- All available qualitative montages inline, with the same case filters and
  shared anatomy intensity scaling. Each montage links to its full resolution
  and the detailed case diagnostics.
- Native registration measurements/settings, transform coverage and boundary
  probes in readable tables, with full machine records available as downloads.

One test can fail several checks, so reason counts need not sum to the number
of failed tests. Grouped maxima are per-case extrema across different images;
they do not constitute a pooled registration-accuracy score. Full JSON remains
available as a secondary download.

Pull-request CI also uploads **site-preview**, a complete offline portal with
all available software reports, even when numerical comparisons fail. Download
that artifact and open `index.html` to review the new global and software pages
before merging. It does not deploy a pull-request build to the public site.
