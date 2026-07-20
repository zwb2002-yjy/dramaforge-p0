# Run BOOT-0 quality gates for backend and frontend.
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "== Directory compliance =="
python (Join-Path $RepoRoot "scripts\check_directory_compliance.py") --root $RepoRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== Backend ruff/mypy/pytest =="
Push-Location (Join-Path $RepoRoot "backend")
try {
    python -m ruff check app tests
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    python -m mypy app
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    python -m pytest -q
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally {
    Pop-Location
}

Write-Host "== Frontend lint/typecheck/test/build =="
Push-Location (Join-Path $RepoRoot "frontend")
try {
    npm.cmd run lint
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    npm.cmd run typecheck
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    npm.cmd run test
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally {
    Pop-Location
}

Write-Host "All quality gates passed."
