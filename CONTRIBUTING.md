# Contributing to DramaForge

Thank you for helping make AI-assisted short-drama creation more reliable.

## Before opening a change

- Read `docs/CURRENT.md` (the single documentation entry point) and the
  authoritative document relevant to your change.
- Agree the scope of large product, schema, workflow, security, or Provider changes
  in the existing issue or current Owner-authorized task; do not duplicate an
  accepted task contract merely to create another tracking artifact.
- Never commit API keys, BYOK ciphertext/plaintext, private media, face embeddings,
  generated evidence containing personal data, or unlicensed model weights.
- Do not make claims about Provider quality, platform support, or AIOS compatibility
  without reproducible evidence.

## Development checks

The repository toolchains are container-owned. Do not create a host Python
environment or install Node dependencies for routine development. Select the
smallest sufficient checks using [DEVELOPMENT.md](docs/DEVELOPMENT.md); batch
related edits before testing and record ordinary results in the conversation.
The full gate, when required by the affected contract or release, is:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_quality_in_docker.ps1
```

It installs locked Python/Node dependencies inside disposable quality images,
starts disposable PostgreSQL and LiteLLM services, and runs the complete
backend/frontend/API/E2E gate. Choose checks proportionate to the change; a
documentation-only edit uses link, source-consistency and policy checks without
starting services. Release candidates still require the full gate described in
[DEVELOPMENT.md](docs/DEVELOPMENT.md).

Use a throwaway `.env` and isolated databases in tests. Pull requests should be
small, explain user-visible behavior, list exact verification commands, and keep
generated artifacts out unless the active contract explicitly requires them.

Routine Owner-authorized integration targets `dev`, currently in fast-development
mode. Protected `dev -> main` releases retain the full checks and Owner-only
approval/merge boundary; see [RELEASE.md](docs/RELEASE.md).

## Contributions and licensing

Unless explicitly stated otherwise, contributions intentionally submitted to
this project are licensed under Apache License 2.0 as described in `LICENSE`.
By contributing, you confirm you have the right to submit the material.
