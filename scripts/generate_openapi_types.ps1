# Generate frontend/src/types/api.ts from the FastAPI OpenAPI schema.
# Requires: backend deps (preferably backend/.venv); Node openapi-typescript via npm.

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $RepoRoot "backend"
$FrontendDir = Join-Path $RepoRoot "frontend"
$SchemaFile = Join-Path $FrontendDir "src\types\openapi.json"
$ExportScript = Join-Path $RepoRoot "scripts\_export_openapi.py"

$VenvPython = Join-Path $BackendDir ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    $Python = $VenvPython
} else {
    $Python = "python"
}

$env:APP_ENV = "test"
$env:SESSION_SECRET = "test-session-secret-32chars-min"
$env:BYOK_FERNET_KEY = "test-byok-fernet-key-replace=="
$env:PYTHONPATH = $BackendDir

& $Python $ExportScript --out $SchemaFile
if ($LASTEXITCODE -ne 0) {
    throw "OpenAPI export failed with exit $LASTEXITCODE"
}

# Use relative paths from frontend/ so Node tools do not mangle non-ASCII absolute paths.
Push-Location $FrontendDir
try {
    & npm.cmd exec -- openapi-typescript ./src/types/openapi.json -o ./src/types/api.ts
    if ($LASTEXITCODE -ne 0) {
        throw "openapi-typescript failed with exit $LASTEXITCODE"
    }
    Write-Host "Generated frontend/src/types/api.ts"
}
finally {
    Pop-Location
}
