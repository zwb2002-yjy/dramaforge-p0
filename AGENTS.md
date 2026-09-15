# DramaForge Codex Rules

## Authority and Reading Order

- The single documentation entry point is [`docs/CURRENT.md`](docs/CURRENT.md).
  Each core domain has exactly one authoritative document listed there.
- Code, migrations, tests, runtime state, and evidence establish current facts;
  the authoritative docs describe intended behavior. When they conflict, code
  wins and the doc must be updated.
- Historical designs, deleted task contracts, reviews, and execution records
  live only in Git history (`git log` / `git show`). They never justify new
  work or override current authority.
- For questions, audits, and non-behavioral wording changes, read only the
  relevant files and authority needed; do not automatically launch services or
  run full product gates.

## Task Scope

- Complete the requested outcome and relevant fixes; do not expand product
  scope, rewrite intended behavior to make a failing test pass, or create
  unrelated follow-up work.
- Preserve the canonical boundaries enforced by the quality gate: single
  creation mainchain, typed proposal / explicit Apply-Save-Formal-Export user
  gates, unified ProductionGraph / NodeRun / ProviderOperation / Artifact,
  Editing never rewrites production truth, ModelManifest / execution identity
  with no silent fallback, retired surfaces stay deleted (see
  `scripts/check_canonical_surface.py`).

## Verification

- Choose verification proportionate to the change (focused tests plus affected
  regression); formal gates required by CI are not reduced.
- Command facts come from [`frontend/package.json`](frontend/package.json),
  [`backend/pyproject.toml`](backend/pyproject.toml), the current
  [CI](.github/workflows/ci.yml) and the
  [container quality config](docker-compose.quality.yml). Do not invent
  commands or substitute host-installed dependencies for container gates.
- Report outcomes truthfully: uncommitted work is reported as such; do not
  fabricate formal completion, evidence, or release claims.

## Git and Ownership

- Routine integration happens on `dev`; `main` only advances through a
  protected `dev -> main` PR. Only `@zwb2002-yjy` approves and merges; agents
  never approve, merge, or record `MERGED`.
- No force push, history rewrite, `reset --hard`, or `clean -fd`. Cleanup is
  limited to the current task's resources.
- Paid provider operations (probe, production, repair) require an explicit
  positive budget and Owner authorization per operation; historical
  authorization never extends to a new task. Never blind-retry a possibly
  billed or `unknown_submission` call.

## Image Evidence Handling

- Treat Playwright screenshots as evidence artifacts, not conversational input.
- Do not use `view_image` for an additional visual spot-check after Playwright
  assertions have already established the result.
- Use Playwright DOM, accessibility, network, console, layout, and business-flow assertions as the primary verification method.
- Before calling `view_image`, inspect the image file size and dimensions.
- Do not call `view_image` on an image larger than 200 KiB or with a long edge over 1200 pixels.
- If automated evidence cannot answer a narrowly defined visual question, create the smallest useful temporary thumbnail or focused crop. The derived image must stay within both limits before it is passed to `view_image`, and only that specific question may be inspected.
- If Playwright evidence and a minimal visual sample are still insufficient or ambiguous, do not load additional or larger images. Ask the user to perform a manual visual review with concrete steps and expected observations, then confirm or modify the implementation from the user's feedback.
- Keep original evidence screenshots unchanged and in place. Use metadata, dimensions, SHA-256 hashes, Playwright assertions, and structured evidence files for primary verification.
- Do not print base64 data, hex dumps, or binary file contents through shell commands.
- Do not use `Get-Content` or equivalent text readers on PNG, JPEG, WebP, MP4, ZIP, or other binary files.
- Do not pass local evidence screenshots to `view_image` when metadata or automated assertions answer the question.
- For evidence under `tmp/p0-evidence/`, verify existence, dimensions, hashes, and assertion results without loading the original pixels into the conversation.

## Local Path and Image Input

- A Windows path is usable by a local tool but is not directly readable by the model or a remote provider.
- `view_image` reads the local file on the client side and packages the image bytes as a data URL, commonly `data:image/<format>;base64,...`, for multimodal model input.
- Treat that encoded image as conversation payload. It can be persisted in the session and replayed on later turns.
- Prefer local metadata and structured test evidence. Use a bounded thumbnail or crop only when visual inspection is necessary.
