# elastix / transformix

Uses Debian bookworm's pinned `elastix=5.0.1-4`. Affine registration parameters
live in `registration.txt`: two resolutions, full sampling, mean squares,
adaptive stochastic gradient descent, 100 iterations, one thread. Transformix
applies known and registered affine maps with order-1/order-0 interpolation,
zero padding and float output.

Parameter files map fixed physical LPS mm to moving physical LPS mm, loaded
with `hint="elastix"`. The original estimated file is retained as the brainhops
input. For each application, a separate parameter file encodes the same world
mapping and the actual output grid (size, spacing, LPS origin and direction).
Changing output grids never changes the registration estimate.

```sh
python -m software.elastix.generate --inputs work/inputs --output work/elastix-fixtures
```

Requires elastix/transformix on PATH and shared numerical requirements.
Generation does not import brainhops; logs, exact registration parameters,
version, landmark errors and independent world-coordinate checks are saved.
Sparse integer rounding disagreements remain strict comparison failures.

## Nonlinear cases

Also exercises all eight supported transform names, B-spline orders 1–3, recursive B-splines, both Euler rotation orders, Compose/Add and nested chains, and native B-spline registration. Add chains are intentionally applied even though brainhops currently rejects that composition mode.
