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
matches the NiftyReg linear probe. It cannot express the ITK/MRtrix combination
of an interior clamp and an exterior cutoff, or transformix's clipped mirror
rule, as one existing public boundary option. Switching to `nearest` or `mirror`
would extend nonzero image values arbitrarily far outside the FOV, which also
disagrees. No image/output patch is added to emulate these missing options.

FLIRT's `-setbackground 0 -paddingsize 1` was investigated: on this build it
changed the padding halo but retained the estimated background farther outside.
Changing those options therefore does not establish an exact zero-boundary
match. The recipe keeps its native convention explicit. FNIRT uses **applywarp**,
which is a distinct image sampler; the affine FLIRT probe must not be treated
as evidence about nonlinear-field extension or all applywarp settings.

Consequently, selecting an existing boundary option cannot remove every edge
warning. The evaluator retains the declared `constant` policy, records the
native rule and its public-API limitation, and reports boundary-only differences
as warnings. It never chooses a mode independently for each anatomical case,
changes the interior mask to conceal errors, or modifies loaded image objects.
Transform-field interpolation/domain extension and integer quantisation can
produce additional discrepancies and remain separate diagnostics.
