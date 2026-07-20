# Run BOOT-0 quality gates for backend and frontend using project toolchains.
# Prefer backend/.venv and frontend npm.cmd — never assume a bare global Python
# has ruff/mypy/pytest installed.
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

function Get-ProjectPython {
    param([string]$Root)
    $candidates = @(
        (Join-Path $Root "backend\.venv\Scripts\python.exe"),
        (Join-Path $Root "backend\.venv\bin\python"),
        (Join-Path $Root ".venv\Scripts\python.exe"),
        (Join-Path $Root ".venv\bin\python")
    )
    foreach ($path in $candidates) {
        if (Test-Path $path) {
            return (Resolve-Path $path).Path
        }
    }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($null -ne $cmd) {
        Write-Warning "No project venv found; falling back to PATH python: $($cmd.Source)"
        return $cmd.Source
    }
    throw "No Python interpreter found. Create backend/.venv and pip install -e `".[dev]`"."
}

function Get-NpmCmd {
    $cmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($null -ne $cmd) {
        return $cmd.Source
    }
    $cmd = Get-Command npm -ErrorAction SilentlyContinue
    if ($null -ne $cmd) {
        return $cmd.Source
    }
    throw "npm/npm.cmd not found on PATH"
}

$Python = Get-ProjectPython -Root $RepoRoot
$Npm = Get-NpmCmd
Write-Host "Using Python: $Python"
Write-Host "Using npm: $Npm"

# Controlled temp root for pytest (avoids Windows PermissionError on shared temps).
$TmpRoot = Join-Path $RepoRoot "tmp"
New-Item -ItemType Directory -Force -Path $TmpRoot | Out-Null
# Remove historical/agent pytest debris (e.g. tmp/codex-pytest-*).
Get-ChildItem -Force $TmpRoot -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "codex-pytest-*" } |
    ForEach-Object {
        try { Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction Stop }
        catch { Write-Warning "Could not remove $($_.FullName): $($_.Exception.Message)" }
    }
$PytestTempRoot = Join-Path $TmpRoot "pytest-basetemp"
$PytestWorkTemp = Join-Path $TmpRoot "pytest-work"
if (Test-Path $PytestTempRoot) {
    Remove-Item -LiteralPath $PytestTempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
if (Test-Path $PytestWorkTemp) {
    Remove-Item -LiteralPath $PytestWorkTemp -Recurse -Force -ErrorAction SilentlyContinue
}
New-Item -ItemType Directory -Force -Path $PytestTempRoot | Out-Null
New-Item -ItemType Directory -Force -Path $PytestWorkTemp | Out-Null
$env:TEMP = $PytestWorkTemp
$env:TMP = $PytestWorkTemp
$env:TMPDIR = $PytestWorkTemp

Write-Host "== Directory compliance =="
& $Python (Join-Path $RepoRoot "scripts\check_directory_compliance.py") --root $RepoRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== Backend ruff/mypy/pytest =="
Push-Location (Join-Path $RepoRoot "backend")
try {
    & $Python -m ruff check app tests
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $Python -m mypy app
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $Python -m pytest -q --basetemp=$PytestTempRoot
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally {
    Pop-Location
}

Write-Host "== Frontend lint/typecheck/test/build =="
Push-Location (Join-Path $RepoRoot "frontend")
try {
    & $Npm run lint
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $Npm run typecheck
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $Npm run test
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $Npm run build
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally {
    Pop-Location
}

# Optional: Playwright only when explicitly requested (slow; separate RECOVERY check).
if ($env:DRAMA_RUN_E2E -eq "1") {
    Write-Host "== Frontend Playwright e2e =="
    Push-Location (Join-Path $RepoRoot "frontend")
    try {
        & $Npm run test:e2e
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    finally {
        Pop-Location
    }
}

Write-Host "All quality gates passed."
exit 0
