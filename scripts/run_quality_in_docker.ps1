param(
    [ValidateSet('Full', 'BackendTests', 'FrontendTests')]
    [string]$Stage = 'Full',
    [string[]]$TestArgs = @(),
    [switch]$OfflineProjectInstall,
    [switch]$KeepArtifacts
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$BuildArgs = @()
if ($OfflineProjectInstall) { $BuildArgs = @('--build-arg', 'QUALITY_UV_OFFLINE=true') }
if ($Stage -eq 'Full' -and $TestArgs.Count -gt 0) {
    throw 'TestArgs is only supported for targeted test stages; Full must not be filtered.'
}
if ($Stage -ne 'Full' -and $KeepArtifacts) {
    throw 'KeepArtifacts is only supported for Full.'
}

. (Join-Path $PSScriptRoot 'quality_output.ps1')

# Targeted feedback builds current source with cached locked dependencies. It
# never starts or tears down a shared Compose stack and cannot call providers.
if ($Stage -ne 'Full') {
    $target = if ($Stage -eq 'BackendTests') { 'backend' } else { 'frontend' }
    $image = "dramaforge-targeted-${target}:local"
    $imageIdFile = Join-Path ([IO.Path]::GetTempPath()) ('df-quality-' + [guid]::NewGuid().ToString('N') + '.iid')
    Push-Location $RepoRoot
    try {
        docker build -f "$target/Dockerfile.quality" -t $image --iidfile $imageIdFile @BuildArgs .
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        # Bind tests to this build, even if another invocation retags the image.
        $imageId = (Get-Content -LiteralPath $imageIdFile -Raw).Trim()
        if ($imageId -notmatch '^sha256:[0-9a-f]{64}$') { throw 'Build did not produce a valid image ID.' }
        if ($target -eq 'backend') {
            if ($TestArgs.Count -eq 0) { $TestArgs = @('tests/unit', '-q') }
            docker run --rm --network none -w /workspace/backend $imageId /workspace/backend/.venv/bin/pytest @TestArgs
        } else {
            docker run --rm --network none -w /workspace/frontend $imageId npm test -- @TestArgs
        }
        exit $LASTEXITCODE
    }
    finally {
        if (Test-Path -LiteralPath $imageIdFile) { Remove-Item -LiteralPath $imageIdFile }
        Pop-Location
    }
}

$PreviousProject = $env:COMPOSE_PROJECT_NAME
$PreviousContract = $env:QUALITY_CONTRACT_DIR
$PreviousBackendImage = $env:QUALITY_BACKEND_IMAGE
$PreviousFrontendImage = $env:QUALITY_FRONTEND_IMAGE
$QualityProject = if ($PreviousProject) { $PreviousProject } else { 'df-quality-' + [guid]::NewGuid().ToString('N') }
if ($QualityProject -notmatch '^df-quality-[a-z0-9-]+$') {
    throw 'Full requires a dedicated COMPOSE_PROJECT_NAME starting with df-quality-.'
}
$QualityContractDir = if ($PreviousContract) {
    if ([IO.Path]::IsPathRooted($PreviousContract)) {
        [IO.Path]::GetFullPath($PreviousContract)
    } else {
        [IO.Path]::GetFullPath((Join-Path $RepoRoot $PreviousContract))
    }
} else {
    Join-Path $RepoRoot "tmp/quality-contract/$QualityProject"
}
$OwnResources = $false
$ChecksPassed = $false
$OutputOwner = $null
Push-Location $RepoRoot
try {
    # Refuse existing resources rather than tearing down another session.
    foreach ($kind in @('container', 'volume', 'network')) {
        $listArgs = @($kind, 'ls', '-q', '--filter', "label=com.docker.compose.project=$QualityProject")
        if ($kind -eq 'container') { $listArgs += '--all' }
        $existing = @(docker @listArgs)
        if ($LASTEXITCODE -ne 0) { throw "Cannot inspect quality $kind resources." }
        if ($existing.Count -gt 0) { throw "Quality project $QualityProject already has $kind resources; select a fresh project." }
    }
    $OutputOwner = New-QualityOutput $QualityContractDir
    $env:COMPOSE_PROJECT_NAME = $QualityProject
    $env:QUALITY_CONTRACT_DIR = $QualityContractDir
    $OwnResources = $true
    if ($env:GITHUB_OUTPUT) {
        # The runner fallback must not clean a project rejected by preflight.
        Add-Content -LiteralPath $env:GITHUB_OUTPUT -Value 'cleanup_owned=true' -Encoding utf8
    }
    # Capture each build's immutable identity, never re-resolve a mutable tag.
    foreach ($target in @('backend', 'frontend')) {
        $iidFile = Join-Path $QualityContractDir "$target.iid"
        docker build -f "$target/Dockerfile.quality" -t "dramaforge-$target-quality:local" --iidfile $iidFile @BuildArgs .
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        $imageId = (Get-Content -LiteralPath $iidFile -Raw).Trim()
        if ($imageId -notmatch '^sha256:[0-9a-f]{64}$') { throw 'Build did not produce a valid image ID.' }
        if ($target -eq 'backend') { $env:QUALITY_BACKEND_IMAGE = $imageId }
        else { $env:QUALITY_FRONTEND_IMAGE = $imageId }
    }

    # Start the stateful test dependencies independently. Waiting for their
    # health state avoids the Windows Compose wait/abort behavior that can keep
    # a completed dependency process attached after backend-quality exits.
    docker compose -f docker-compose.quality.yml up -d postgres-quality redis-quality minio-quality
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    foreach ($service in @("postgres-quality", "redis-quality", "minio-quality")) {
        $dependencyContainer = (docker compose -f docker-compose.quality.yml ps -q $service).Trim()
        if ([string]::IsNullOrWhiteSpace($dependencyContainer)) {
            throw "$service container was not created"
        }
        $healthy = $false
        for ($attempt = 0; $attempt -lt 45; $attempt++) {
            $health = (docker inspect --format '{{.State.Health.Status}}' $dependencyContainer 2>$null).Trim()
            if ($health -eq "healthy") {
                $healthy = $true
                break
            }
            Start-Sleep -Seconds 1
        }
        if (-not $healthy) {
            throw "$service did not become healthy"
        }
    }

    # Backend publishes the OpenAPI contract into the shared contract directory.
    docker compose -f docker-compose.quality.yml run --rm --no-deps backend-quality
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    # Frontend consumes the contract only after backend quality has completed.
    docker compose -f docker-compose.quality.yml run --rm --no-deps frontend-quality
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    # Real TLS and MinIO SDK streams; isolated synthetic 256MiB fixtures.
    docker compose -f docker-compose.quality.yml up --no-build --abort-on-container-exit --exit-code-from media-resource-quality media-resource-quality
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    # Exercise the deployed Nginx config against a synthetic auth upstream.
    docker compose -f docker-compose.quality.yml up --no-build --abort-on-container-exit --exit-code-from auth-gateway-integration-quality auth-gateway-integration-quality
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    # The pinned official LiteLLM image is exercised without an external
    # provider; the integration fixture supplies deterministic mock models.
    docker compose -f docker-compose.quality.yml up --no-build --abort-on-container-exit --exit-code-from litellm-integration-quality litellm-quality litellm-integration-quality
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $ChecksPassed = $true
}
finally {
    $CleanupExit = 0
    if ($OwnResources) {
        docker compose -f docker-compose.quality.yml down --volumes --remove-orphans
        $CleanupExit = $LASTEXITCODE
    }
    $env:COMPOSE_PROJECT_NAME = $PreviousProject
    $env:QUALITY_CONTRACT_DIR = $PreviousContract
    $env:QUALITY_BACKEND_IMAGE = $PreviousBackendImage
    $env:QUALITY_FRONTEND_IMAGE = $PreviousFrontendImage
    Pop-Location
    if ($ChecksPassed -and $CleanupExit -ne 0) {
        throw "Quality checks passed but resource cleanup failed (exit $CleanupExit)."
    }
    if ($OwnResources -and $ChecksPassed -and -not $KeepArtifacts) {
        Clear-QualityOutput $RepoRoot $QualityContractDir $OutputOwner
        # Fixed cache tags may move; runtime commands above used this run's immutable IDs.
    }
}
