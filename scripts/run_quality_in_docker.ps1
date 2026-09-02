param()

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$QualityContractDir = Join-Path $RepoRoot "tmp\quality-contract"
New-Item -ItemType Directory -Force -Path $QualityContractDir | Out-Null
$env:QUALITY_CONTRACT_DIR = "./tmp/quality-contract"
Push-Location $RepoRoot
try {
    docker compose -f docker-compose.quality.yml down --volumes --remove-orphans
    docker compose -f docker-compose.quality.yml build backend-quality frontend-quality
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    # Start PostgreSQL independently.  Waiting for its health state avoids the
    # Windows Compose wait/abort behavior that can keep a completed dependency
    # process attached after backend-quality exits.
    docker compose -f docker-compose.quality.yml up -d postgres-quality
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $postgresContainer = (docker compose -f docker-compose.quality.yml ps -q postgres-quality).Trim()
    if ([string]::IsNullOrWhiteSpace($postgresContainer)) {
        throw "postgres-quality container was not created"
    }
    $healthy = $false
    for ($attempt = 0; $attempt -lt 45; $attempt++) {
        $health = (docker inspect --format '{{.State.Health.Status}}' $postgresContainer 2>$null).Trim()
        if ($health -eq "healthy") {
            $healthy = $true
            break
        }
        Start-Sleep -Seconds 1
    }
    if (-not $healthy) {
        throw "postgres-quality did not become healthy"
    }

    # Backend publishes the OpenAPI contract into the named quality volume.
    docker compose -f docker-compose.quality.yml run --rm --no-deps backend-quality
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    # Frontend consumes the contract only after backend quality has completed.
    docker compose -f docker-compose.quality.yml run --rm --no-deps frontend-quality
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    # The pinned official LiteLLM image is exercised without an external
    # provider; the integration fixture supplies deterministic mock models.
    docker compose -f docker-compose.quality.yml up --no-build --abort-on-container-exit --exit-code-from litellm-integration-quality litellm-quality litellm-integration-quality
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally {
    docker compose -f docker-compose.quality.yml down --volumes --remove-orphans
    Pop-Location
}
