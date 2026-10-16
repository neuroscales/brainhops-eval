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
