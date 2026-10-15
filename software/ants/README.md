# ANTs reference generation

This folder owns antsRegistration/antsApplyTransforms commands, dependencies,
and the SIF entrypoint. The pinned ANTs image supplies binaries. SimpleITK is
used for ITK transform serialization, conversion checks, and masks; expected
resampled images are produced by antsApplyTransforms.

From the repository root, with shared tooling installed, ANTs binaries on PATH,
its library path configured, and one ITK thread:

```sh
pip install -r software/ants/requirements.txt
ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS=1 ANTS_RANDOM_SEED=1729 \
  python -m software.ants.generate --inputs work/inputs --output work/fixtures
```

The container definition sets these paths and runtime options automatically.
No SimpleITK raster defaults are attributed to ANTs. This recipe never imports
brainhops; see `../README.md` for the common bundle contract.
