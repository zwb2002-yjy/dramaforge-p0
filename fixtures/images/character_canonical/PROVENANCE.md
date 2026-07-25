# S0-A Local Fixture Provenance

The image binaries in this directory are intentionally ignored. Recreate them with:

```powershell
python .\scripts\acquire_s0_face_fixtures.py
```

The script materializes public test assets from `deepinsight/insightface` commit
`1456819742fd09bc4ad5293856a143a3e807c78e`. The exact upstream source paths are
the `IDENTITY_SOURCES` and `NO_FACE_SOURCE` constants in that script. The source
revision, output IDs, horizontal-flip and 6 percent center-crop transforms are
therefore deterministic and reviewable without committing image bytes.

The script uses a locally cached Git object when possible. When a partial clone
does not contain an image blob, it retrieves the same immutable path from
`raw.githubusercontent.com` at that exact commit.

`*_v00` samples are direct upstream images. `*_flip` and `*_crop` are derived
from the corresponding direct image. `anom_noface_*` is the upstream versioned
`crop/no_face.png`; `anom_lowq_*` is the same no-face image with deterministic
Gaussian blur. All ten are truthfully annotated as `no_face`; detector output is
recorded separately by the calibration runner.

This collection exists only to calibrate the S0-A model behavior. It is not
production identity data. Reports must include only fixture IDs and aggregated
metrics, never raw images or embedding vectors.
