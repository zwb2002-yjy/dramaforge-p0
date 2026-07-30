# P0 Gate Audit Sanitization

Task ID: `p0-gate-audit-sanitization`

## Outcome

Historical and future non-Git P0 evidence does not contain an API-key fragment,
download grant token, or raw grant response. Historical `docs/acceptance` files
are not used as current formal Gate evidence.

## Scope

- Remove tracked historical evidence files that contain sensitive runtime data or
  are not source-bound to the current commit.
- Ensure the Agnes smoke and legacy proof scripts write reports outside tracked
  `docs/acceptance` and omit grant credentials.
- Add focused regression coverage for evidence redaction behavior.

## Out of Scope

- Running paid Provider calls.
- Producing formal P0 evidence or closing any P0 Gate.
- Changing the P0 Gate checker, deployment stack, Provider implementation, or product
  runtime.

## Preconditions

- `main` and `origin/main` are synchronized at task creation.
- The task runs only in `agent/p0-gate-audit-sanitization`.

## Acceptance Evidence

- Targeted evidence-redaction tests pass.
- `rg` finds no `key_prefix` or persisted download-grant token in tracked
  acceptance evidence.
- `git diff --check` passes.

## Completion Definition

The scoped scripts cannot persist credentials in tracked evidence, historical
unsafe evidence has been removed, and the focused regression tests pass on a
clean task commit.
