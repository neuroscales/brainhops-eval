# Dataset sources

The default suite uses an analytic asymmetric phantom, without downloads.
`sources.json` also pins a small NiBabel anatomical image by upstream commit
and SHA256, so the download and augmentation path is usable immediately.
The upstream [COPYING](https://github.com/nipy/nibabel/blob/7b5060e4bb105ed0c08c203db3dc5cf536d9c2aa/COPYING)
contains attribution and license details; its MIT notice is reproduced in
`nibabel-LICENSE.txt`. Source provenance travels into the fixture bundle.

## Adding OpenNeuro data

Add individual files, not an entire dataset checkout. Each entry requires:

```json
{
  "url": "https://<snapshot-specific-download-url>",
  "filename": "dataset-snapshot-subject-T1w.nii.gz",
  "sha256": "<64-character-SHA256-of-the-actual-NIfTI-bytes>",
  "version": "<OpenNeuro accession and immutable snapshot>",
  "license": "<license from that dataset snapshot>",
  "license_url": "https://<snapshot-license>",
  "attribution": "<dataset authors and citation>"
}
```

Check the source's redistribution terms before releasing derived fixtures.
Use an actual binary download endpoint: a GitHub/DataLad annex pointer is not
the NIfTI payload. Pin the snapshot and checksum even if a service exposes only
a mutable download URL. Supply its citation and license notice with any
redistributed bundle. The downloader verifies the checksum before caching,
repairs corrupted cached files, and writes an adjacent `.source.json` record.

Then run:

```sh
source_path=$(brainhops-eval fetch your-dataset-entry)
brainhops-eval generate --source "$source_path" --output work/inputs
```

The current anatomical path accepts a finite, scalar 3D NIfTI, scales its
1st–99.5th percentiles to 0–1000, recentres its frame, and samples it onto the
diagnostic grids. The original affine and intensity scaling are recorded.
PNG/NPY cases remain synthetic even when the 3D source is anatomical.

To expose another entry in the hosted workflow, add its name to the workflow
dataset choices and validation list. No OpenNeuro accession or checksum is
invented or silently downloaded by the initial suite.

