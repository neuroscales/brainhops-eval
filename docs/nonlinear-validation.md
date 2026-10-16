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
