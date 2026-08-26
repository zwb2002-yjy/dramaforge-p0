# Contributing to DramaForge

Thank you for helping make AI-assisted short-drama creation more reliable.

## Before opening a change

- Read `DramaForge总开发文档.md`, `docs/README.md`, the seven-plan program under
  `docs/plans/professional-program-v2/`, and the current Task Contract.
- Open an issue for large product, schema, workflow, security, or Provider changes.
- Never commit API keys, BYOK ciphertext/plaintext, private media, face embeddings,
  generated evidence containing personal data, or unlicensed model weights.
- Do not make claims about Provider quality, platform support, or AIOS compatibility
  without reproducible evidence.

## Development checks

```powershell
cd backend
uv sync --locked --extra dev
uv run ruff check app tests
uv run mypy app
uv run pytest tests/unit -q

cd ..\frontend
npm ci
npm run lint
npm run typecheck
npm test
npm run build
```

Container changes must also pass:

```powershell
python scripts/init_env.py
docker compose config --quiet
docker compose build
```

Use a throwaway `.env` and isolated databases in tests. Pull requests should be
small, explain user-visible behavior, list exact verification commands, and keep
generated artifacts out unless the active contract explicitly requires them.

## Contributions and licensing

Unless explicitly stated otherwise, contributions intentionally submitted to
this project are licensed under Apache License 2.0 as described in `LICENSE`.
By contributing, you confirm you have the right to submit the material.
