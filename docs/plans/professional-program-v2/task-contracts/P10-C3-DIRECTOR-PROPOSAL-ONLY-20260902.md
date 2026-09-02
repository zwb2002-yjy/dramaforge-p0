# P10-C3 — Director proposal-only convergence

**Status:** USER-AUTHORIZED / IN PROGRESS
**Parent:** P10 legacy hard removal
**Canonical boundary:** Director Assistant → suggestion/proposal → explicit user apply

## Outcome

The former controlled Director product is removed. The Director package keeps
only provider-neutral creative capability definitions, Shot suggestions,
Assistant context/thread/message persistence, and typed proposal commands. It
does not own workflow stages, approvals, budgets, production batches, repair
authorization, or media export.

## Implemented boundary

- director.py exposes only the read-only Shot suggestion endpoint.
- Thread/message models live in director/assistant_models.py.
- Graph templates used by the canonical workbench live in production/templates.py.
- Old workflow, budget, trial, production, repair, and export services/routes are
  deleted; their tests are removed or replaced by canonical Assistant tests.
- All direct Shot operations use the canonical Workbench/Review/Repair services
  without a legacy gate.

## Verification

- Generated OpenAPI contains no controlled Director route or retired response
  model.
- Canonical suggestion, proposal, editing-suggestion, and Golden-project tests
  remain covered.
- No runtime import references deleted Creation or controlled Director modules.
