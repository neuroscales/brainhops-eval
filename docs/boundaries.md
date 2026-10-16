# Image boundary conventions

The previous blanket description “zero boundary” was insufficient. A nonzero
float ramp sampled at fractional voxels across both image edges distinguishes
padding from clipping and avoids integer rounding. Every native recipe now
records the actual samples and model residuals in `boundary-probes.json`.
These are native application probes, not anatomy-dependent choices of a mode
that happens to pass a failed case.

Measured with the pinned native runtimes, for linear image interpolation:

| Software | Measured convention |
| --- | --- |
| SimpleITK 2.5.2 / ANTs 2.6.0 | Clamp to edge values within `[-0.5, n-0.5)`; zero outside |
| elastix 5.0.1, FinalBSplineInterpolator order 1 | Mirror interpolation inside the same half-voxel extent; zero outside |
| NiftyReg 2.1.2, `-pad 0` | Zero-extended grid interpolation, including fractional fading across the edge |
| MRtrix 3.0.3 | Clamp within the strict half-voxel extent; zero at/outside its endpoints |
| FSL FLIRT 6.0.4 | Native estimated background outside the voxel-centre FOV; this was 29 on the probe ramp, not zero |

Nearest-neighbour sampling is also probed. Exact half-voxel endpoints can differ
between packages even when other samples agree. The full sampled values and
limits remain available rather than rounding coordinates to hide those cases.

brainhops currently maps `bound="constant"` (or numeric zero) to SciPy's
`grid-constant`: interpolation includes zero-valued neighbours. This exactly
matches the NiftyReg linear probe. The public `clip` option separately limits
the sampled voxel extent, allowing nearest/mirror extension inside that extent. Switching to `nearest` or `mirror`
would extend nonzero image values arbitrarily far outside the FOV, which also
disagrees. The evaluator uses that upstream option directly, without an image/output patch.

FLIRT's `-setbackground 0 -paddingsize 1` was investigated: on this build it
changed the padding halo but retained the estimated background farther outside.
Changing those options therefore does not establish an exact zero-boundary
match. The recipe keeps its native convention explicit. FNIRT uses **applywarp**,
which is a distinct image sampler; the affine FLIRT probe must not be treated
as evidence about nonlinear-field extension or all applywarp settings.

## Declared closest policies

The evaluator now selects a fixed policy by package and image interpolation
order. It does not search for the best mode on individual anatomical outputs.

| Sampler | Image interpolation | `bound` | `clip` |
| --- | --- | --- | --- |
| ITK / ANTs | Linear | `nearest` | `0.5` |
| transformix | Linear B-spline | `mirror` | `0.5` |
| MRtrix | Linear | `nearest` | `0.5` |
| The above four | Nearest neighbour | `constant` | `None` |
| NiftyReg | Linear / nearest neighbour | `constant` | `None` |
| FLIRT | Linear / nearest neighbour | `constant` (approximate) | `None` |
| FNIRT applywarp | Linear / nearest neighbour | `constant` | `None` |

Clipping was merged in [brainhops PR #485](https://github.com/neuroscales/brainhops/pull/485),
upstream commit `ab2628b11b18ed9e93960fcb562023f76fee6357`.
The evaluator detects the public `reslice` signature. A selected version without
`clip` uses the legacy grid-zero approximation; the report records both the
requested policy and this capability fallback. No patches are applied to the
version under evaluation. Native reader objects are still passed directly to
`source(pull).reslice(reference, ...)`.

`clip` uses a **closed** interval `[-lower, n - 1 + upper]`. On the independent
float ramp, clipped nearest/mirror interpolation reproduces every non-endpoint
linear sample from ITK/ANTs, transformix and MRtrix exactly. The native ITK and
transformix intervals exclude their upper endpoint; MRtrix excludes both.
The evaluator preserves these discrepancies rather than nudging coordinates,
adding an epsilon, or altering the interior mask. On a probe that deliberately
samples endpoints, RMSE therefore need not decrease even though all other edge
samples now match. Nearest-neighbour grid-zero already matches the ITK/ANTs/
transformix probe, so those policies stay unchanged; MRtrix retains one endpoint
mismatch.

FLIRT has no exact match in these options. Mirror extrapolation reduces the
synthetic ramp RMSE (linear 9.58453 to 6.65814), but validation on four unchanged
anatomical cases showed boundary NRMSE rising from 0.0058–0.0101 to
0.0123–0.0227, with interior metrics unchanged. A ramp-only numerical optimum
therefore does not establish the right native rule. FLIRT retains the fixed
grid-zero approximation until its estimated background and centre-FOV cutoff
can be represented. It does not switch modes on individual case results.
FNIRT uses a distinct sampler and retains its separate policy.

Boundary-only discrepancies remain warnings. Integer quantisation and nonlinear
transform-field interpolation/domain extension can cause additional differences
and remain separate diagnostics.

## Focused anatomical validation

Using upstream merged brainhops commit `ab2628b11b18ed9e93960fcb562023f76fee6357`
against unchanged native fixture outputs, the five-case SimpleITK subset lost
all five boundary warnings. Integer boundary maximum errors of 24–38 became
zero; the downsampled float case fell from 3.09531 to 0.000188112.

The five-case elastix subset also lost all five boundary warnings. Integer
boundary maximum errors of 35–40 became zero; the downsampled float case fell
from 66.1836 to 0.00019455. Its two one-voxel interior integer disagreements
remain failures. Every case retained exactly the previous interior maximum
error and integer mismatch count. These subsets test the boundary policy;
they are not a claim that the full interoperability matrix now passes.


## Upstream measurements, not a local clipping implementation

Native generation remains independent of brainhops. At evaluation time, edge
probes are resliced through `io.images.load(...).reslice(...)` from the selected
upstream installation, using its public `bound` and `clip` options. Reports
plot those actual brainhops samples and show their measured maximum error,
RMSE, mismatch count and exact options in `boundary-probes.json`. Probe reader
objects are used unchanged, just like the anatomical cases.

The duplicated closed-clipping formulas have been removed from the native
probe models. Remaining independent models classify native software behavior;
they do not implement or override brainhops resampling. Legacy reports lacking
actual brainhops probe samples explicitly label their old diagnostic curve.
CI checks out upstream `main`; workflow dispatch still accepts any upstream
commit, tag or branch and records its resolved SHA.
