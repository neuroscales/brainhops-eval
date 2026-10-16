# SimpleITK reference generation

This folder owns SimpleITK registration, resampling, dependencies, and the SIF
entrypoint. It generates ITK TFM/HDF5 transforms, NIfTI reference outputs, and
PNG reader-default probes. NPY is not tested as an image format. Shared ITK bundle bookkeeping is in `../_shared`.

From the repository root, with shared tooling installed:

```sh
pip install -r software/simpleitk/requirements.txt
python -m software.simpleitk.generate --inputs work/inputs --output work/fixtures
```

Or build `software/simpleitk/container.def` and use its runscript as described
in `../README.md`. The recipe never imports brainhops.

## Nonlinear cases

Also generates native B-spline registration, all supported ITK transform families, dense/inverse fields, mixed composites and 2D PNG cases. See the nonlinear coverage matrix in `../README.md`.
