param()

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $RepoRoot
try {
    docker compose -f docker-compose.quality.yml build backend-quality frontend-quality
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    # Backend must finish first so it can publish the generated OpenAPI
    # contract.  Running both services with --exit-code-from frontend would
    # abort as soon as the successful backend container exits.
    docker compose -f docker-compose.quality.yml up --no-build --abort-on-container-exit --exit-code-from backend-quality postgres-quality backend-quality
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    docker compose -f docker-compose.quality.yml run --rm --no-deps frontend-quality
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally {
    docker compose -f docker-compose.quality.yml down --remove-orphans
    Pop-Location
}
