# Nonlinear validation

The nonlinear recipes expand the affine-only baseline. The family matrix and
native capability gaps are documented in [software/README.md](../software/README.md).
A representation is only listed as tested after its native application succeeds.
The evaluator applies transforms directly to the image reader's loaded objects.

The tooling suite has 30 passing tests. Additional native checks verify physical
ITK serialization, nonzero curvature, noncommuting composition, and independent
RAS mappings for known FSL/NiftyReg fields. FSL known relative/absolute applications
on original and downsampled moving grids agree with independent SciPy world-space
sampling within 0.003 intensity units (enforced limit 0.01).

Local evaluation uses brainhops commit `dfa04d98cc5ce6a383067ebbbd283890bf5165a3`
from upstream PR #473, so its affine conversion fix does not obscure nonlinear
results. This commit is selected externally; no patch is applied by this repository.

New genuine failures remain strict failures/errors. Initial examples:

- ITK HDF5 spline names such as `BSplineTransform_double_3_3_0` have an extra
  order suffix that the reader currently rejects.
- FSL `convertwarp` writes valid dense fields with intent 0; the FNIRT reader
  raises `Unsupported FNIRT intent code 0` even with an explicit deformation hint.
- Some native MRtrix compressed/detached field representations raise
  `The MRtrix header has no END line`.
- elastix `HowToCombineTransforms "Add"` is explicitly rejected by brainhops;
  it is exercised because transformix can apply it.
- Native integer interpolation/quantisation discrepancies can still produce
  interior failures. Boundary-only differences remain nonblocking warnings.

These examples are diagnostic observations, not a complete root-cause analysis
of every numerical discrepancy. Per-case JSON, tracebacks and montages in Actions
artifacts are authoritative for the selected brainhops version. Native build
omissions (for example Debian elastix's missing Similarity/AffineLog/AffineDTI
components, SimpleITK's missing 2D logarithmic-scale factory, and ANTs' missing noncubic spline factories) are recorded separately
in `coverage.json`, with native command logs; they are not claimed as passing tests.

## Completed local comparison

All 1,407 native application cases completed against the commit above. Counts
include the existing affine baseline. SimpleITK's 498 volumetric and 35 PNG cases
were evaluated separately after repairing the optional native 2D factory handling;
the recipe and hosted workflow generate them together. Warning cases pass the
interior comparison; errors are reader/application exceptions.

| Native backend | Pass | Warning | Fail | Error | Total |
| --- | ---: | ---: | ---: | ---: | ---: |
| SimpleITK | 96 | 162 | 163 | 112 | 533 |
| ANTs | 91 | 112 | 179 | 50 | 432 |
| FSL | 7 | 9 | 26 | 42 | 84 |
| NiftyReg | 32 | 0 | 87 | 0 | 119 |
| elastix | 15 | 53 | 37 | 7 | 112 |
| MRtrix | 16 | 29 | 43 | 39 | 127 |

These are failure-discovery suites, not a green compatibility claim. Coverage
manifests also include native-supported types beyond current brainhops readers
(for example quaternion/composed-scale-skew ITK classes); their rejection is
visible rather than silently omitted. All 30 tooling tests pass independently.
All six container definitions built successfully in hosted runs; ANTs, FSL,
NiftyReg, elastix and MRtrix native generation also passed there. The SimpleITK
2D factory handling fix passed the local complete PNG generation regression;
its updated hosted run is pending.

## Follow-up investigation

The order-0 SimpleITK initializer places its coefficient grid billions of mm
away (an unsigned `order - 1` underflow), and the native transform remains an
identity even after repairing the coefficient origin, due to its valid-region
calculation. The 24 SimpleITK order-0 application cases in the historical table
above were native no-ops, so they are not meaningful nonlinear coverage. The
recipe now probes native movement and records these as capability gaps. No
brainhops objects or reference values are modified to imitate that defect.
The current meaningful inventory therefore excludes those 24 cases.

Upstream fixes have merged as brainhops PRs #475 (detached MRtrix EOF headers),
#476 (ITK B-spline order and 2D field systems), #477 (intent-0 FSL dense fields
and retained deformation-type options), and #478 (additional native ITK affine
families). The hosted evaluation now tests main including these fixes; evaluation never applies patches implicitly.
