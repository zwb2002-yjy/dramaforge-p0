# Third-party notices

DramaForge is distributed under Apache License 2.0. Its dependency manifests
(`backend/pyproject.toml`, `backend/uv.lock`, `frontend/package.json`, and
`frontend/package-lock.json`) are the authoritative inventory of bundled
software dependencies for a source revision.

Release automation generates a machine-readable SPDX SBOM. Review that SBOM and
the license files shipped by each dependency before redistributing a built
image. Provider services, optional local models, voices, fonts, input media and
generated media are not relicensed by DramaForge.

In particular, this repository and its default container images do not contain
or download InsightFace pretrained model weights. An operator who supplies
optional weights is responsible for their provenance, license and permitted
use.
