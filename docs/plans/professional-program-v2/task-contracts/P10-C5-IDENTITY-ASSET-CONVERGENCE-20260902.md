# P10-C5 — Identity asset convergence

**Status:** COMPLETE
**Parent:** P10 legacy hard removal

## Outcome

Identity is represented only by the generic Asset graph:

`Asset → AssetVersion → AssetVersionReference → ShotReferenceBinding`.

Script import records story text only. It does not create a lead-character row
or guess a reference from a name or prompt.

## Implemented boundary

- The synchronous characters/lead API and assets.characters service are removed.
- Character and CharacterReference ORM models are removed.
- Asset-card reads use only the current AssetVersion references.
- Participation payloads identify character assets with asset_id and require an
  explicit AssetVersion for visible subjects.
- Golden and workflow tests seed and verify AssetVersionReference rows directly.
