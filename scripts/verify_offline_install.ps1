# Stage 15 local install verification: build the exact candidate images, assemble the
# offline bundle exactly as the release workflow does, then install it into a clean
# directory through install.ps1 -Offline and assert the Compose stack becomes healthy.
#
# This is a local reproduction for development verification. It does not replace the
# Release workflow run, the published artifacts or the GitHub required checks.
#
#   pwsh -File scripts/verify_offline_install.ps1 -Port 8091 -Version 0.1.0
param(
    [int]$Port = 8091,
    [string]$Version = "0.1.0",
    [string]$WorkDir = "",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$sha = (git -C $repo rev-parse HEAD).Trim()
$tag = "sha-$($sha.Substring(0, 8))"

$work = if ($WorkDir) { $WorkDir } else { Join-Path $repo "tmp\stage15-install-$tag" }
$bundle = Join-Path $work "bundle"
$project = "dramaforge-install-$tag"

Write-Host "candidate : $sha"
Write-Host "tag       : $tag"
Write-Host "work dir  : $work"
Write-Host "project   : $project on port $Port"

if (Test-Path $work) { Remove-Item -Recurse -Force $work }
New-Item -ItemType Directory -Force -Path $bundle, (Join-Path $bundle "infra\litellm") | Out-Null

# A previous attempt leaves its own volumes behind, and the freshly rendered .env
# carries new database credentials: tear the project down so the install starts
# from the clean state every time.
$previous = $ErrorActionPreference
$ErrorActionPreference = "Continue"
docker compose -p $project down -v --remove-orphans 2>&1 | Out-Null
$ErrorActionPreference = $previous

$backendImage = "dramaforge-backend:$tag"
$frontendImage = "dramaforge-frontend:$tag"

if (-not $SkipBuild) {
    Write-Host "`n== building the exact candidate images =="
    docker build -f backend/Dockerfile --build-arg DRAMAFORGE_SOURCE_COMMIT=$sha --build-arg DRAMAFORGE_VERSION=$Version -t $backendImage backend
    if ($LASTEXITCODE -ne 0) { throw "backend image build failed" }
    docker build -f frontend/Dockerfile --build-arg DRAMAFORGE_SOURCE_COMMIT=$sha --build-arg DRAMAFORGE_VERSION=$Version -t $frontendImage frontend
    if ($LASTEXITCODE -ne 0) { throw "frontend image build failed" }
}

Write-Host "`n== assembling the offline bundle =="
$common = @(
    "docker-compose.yml", "docker-compose.offline.yml", ".env.example",
    "install.ps1", "install.sh", "LICENSE", "NOTICE"
)
foreach ($file in $common) {
    Copy-Item (Join-Path $repo $file) (Join-Path $bundle $file) -Force
}
Copy-Item (Join-Path $repo "infra\litellm\config.yaml") (Join-Path $bundle "infra\litellm\config.yaml") -Force

$runtimeImages = @(
    $backendImage, $frontendImage,
    "postgres:15-alpine", "redis:7-alpine",
    "quay.io/minio/minio:RELEASE.2024-12-18T13-15-44Z",
    "ghcr.io/berriai/litellm:v1.96.0"
)
foreach ($image in $runtimeImages) {
    docker image inspect $image > $null 2>&1
    if ($LASTEXITCODE -ne 0) { throw "runtime image missing locally: $image" }
}

$headsOutput = docker run --rm -v "${repo}:/workspace" -w /workspace/backend $backendImage python -c @"
from alembic.config import Config
from alembic.script import ScriptDirectory
heads = ScriptDirectory.from_config(Config('alembic.ini')).get_heads()
print('\n'.join(heads))
"@ 2>&1
$headLines = @($headsOutput | Where-Object { $_ -match '^\S+$' -and $_ -notmatch '^\s*$' })
if (-not $headLines) { throw "migration head could not be resolved: $headsOutput" }
if ($headLines.Count -ne 1) {
    throw "release requires exactly one alembic head; found $($headLines.Count): $($headLines -join ', ')"
}
$migrationHead = $headLines[0].Trim()
Write-Host "migration head: $migrationHead"

$backendDigest = (docker images --no-trunc --format "{{.ID}}" $backendImage | Select-Object -First 1).Trim()
$frontendDigest = (docker images --no-trunc --format "{{.ID}}" $frontendImage | Select-Object -First 1).Trim()

$manifestPath = Join-Path $work "release-manifest.json"
docker run --rm -v "${repo}:/workspace" -w /workspace $backendImage python /workspace/scripts/release_contract.py manifest `
    --version $Version --source-commit $sha --migration-head $migrationHead `
    --backend-image "dramaforge-backend" --backend-tag $tag --backend-digest $backendDigest `
    --frontend-image "dramaforge-frontend" --frontend-tag $tag --frontend-digest $frontendDigest `
    --output-file "/workspace/$($manifestPath.Replace($repo + '\', '').Replace('\', '/'))"
if ($LASTEXITCODE -ne 0) { throw "release manifest generation failed" }
Copy-Item $manifestPath (Join-Path $bundle "release-manifest.json") -Force

$envLines = @(
    "DRAMAFORGE_VERSION=$Version",
    "DRAMAFORGE_SOURCE_COMMIT=$sha",
    "DRAMAFORGE_BACKEND_IMAGE=$backendImage",
    "DRAMAFORGE_FRONTEND_IMAGE=$frontendImage"
)
# BOM-free: the installer keeps the first parsed key as-is, so a BOM there hides
# DRAMAFORGE_VERSION from it.
[System.IO.File]::WriteAllText(
    (Join-Path $bundle "release.env"),
    (($envLines -join "`n") + "`n"),
    [System.Text.UTF8Encoding]::new($false)
)

Write-Host "`n== saving runtime images to images.tar.gz (single pass) =="
$tarPath = Join-Path $work "images.tar"
docker save -o $tarPath $runtimeImages
if ($LASTEXITCODE -ne 0) { throw "docker save failed" }
$tarBytes = (Get-Item $tarPath).Length
Write-Host "images.tar: $tarBytes bytes"
$source = [System.IO.File]::OpenRead($tarPath)
$target = [System.IO.File]::Create((Join-Path $bundle "images.tar.gz"))
$gzip = New-Object System.IO.Compression.GZipStream($target, [System.IO.Compression.CompressionLevel]::Optimal)
$source.CopyTo($gzip)
$gzip.Dispose(); $target.Dispose(); $source.Dispose()
Remove-Item $tarPath -Force
$gzPath = Join-Path $bundle "images.tar.gz"
$gzBytes = (Get-Item $gzPath).Length
Write-Host "images.tar.gz: $gzBytes bytes"

Write-Host "`n== verifying gzip integrity by streaming the whole archive =="
$archiveBytes = 0
$archiveHash = $null
$input = [System.IO.File]::OpenRead($gzPath)
try {
    $gzip = New-Object System.IO.Compression.GZipStream($input, [System.IO.Compression.CompressionMode]::Decompress)
    try {
        $hasher = [System.Security.Cryptography.SHA256]::Create()
        $buffer = New-Object byte[] 1048576
        while (($read = $gzip.Read($buffer, 0, $buffer.Length)) -gt 0) {
            $null = $hasher.TransformBlock($buffer, 0, $read, $buffer, 0)
            $archiveBytes += $read
        }
        $null = $hasher.TransformFinalBlock(@(), 0, 0)
        $archiveHash = ([BitConverter]::ToString($hasher.Hash)).Replace("-", "").ToLower()
    } finally { $gzip.Dispose() }
} finally { $input.Dispose() }
$gzipIntegrityOk = ($archiveBytes -eq $tarBytes)
Write-Host "uncompressed: $archiveBytes bytes (tar: $tarBytes) sha256 $($archiveHash.Substring(0,16))"
if (-not $gzipIntegrityOk) { throw "images.tar.gz does not decompress to the saved tar" }

Write-Host "`n== installing the bundle into a clean directory =="
# Render .env with the bundle's own generator (the installer does the same) but on
# this verification's port: the live board already owns 8080, and the installer
# preserves an .env that is already present.
# Render .env with the bundle's own generator. The template is copied into the
# container and redirected by file: piping it through the PowerShell pipeline
# rewrites bytes, and a container created without stdin never sees the template.
$probe = "df-env-probe-$($sha.Substring(0,8))"
$previous = $ErrorActionPreference
$ErrorActionPreference = "Continue"
docker rm -f $probe 2>&1 | Out-Null
$ErrorActionPreference = $previous
docker create --name $probe $backendImage sh -c `
    "python -m app.install_env --version $Version --source-commit $sha --backend-image $backendImage --frontend-image $frontendImage < /tmp/template.env" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "could not create the env rendering container" }
docker cp (Join-Path $bundle ".env.example") "${probe}:/tmp/template.env"
$rendered = @(docker start -a $probe 2>&1)
$renderExit = $LASTEXITCODE
docker rm $probe | Out-Null
if ($renderExit -ne 0 -or $rendered.Count -eq 0) { throw "failed to render the bundle .env: $rendered" }
$envLines = @($rendered -split "`n")
for ($i = 0; $i -lt $envLines.Count; $i++) {
    if ($envLines[$i] -match '^DRAMAFORGE_PORT=') { $envLines[$i] = "DRAMAFORGE_PORT=$Port" }
    elseif ($envLines[$i] -match '^DRAMAFORGE_PUBLIC_ORIGIN=') { $envLines[$i] = "DRAMAFORGE_PUBLIC_ORIGIN=http://localhost:$Port" }
}
# BOM-free: a BOM hides the first key from docker compose --env-file parsing.
[System.IO.File]::WriteAllText(
    (Join-Path $bundle ".env"),
    (($envLines -join "`n") + "`n"),
    [System.Text.UTF8Encoding]::new($false)
)
$portInEnv = (Select-String -Path (Join-Path $bundle ".env") -Pattern '^DRAMAFORGE_PORT=(.+)$').Matches.Groups[1].Value
Write-Host "install port (from .env): $portInEnv"
if ($portInEnv -ne "$Port") { throw "bundle .env did not take port $Port" }

Push-Location $bundle
try {
    # Pin the compose project so the install cannot land in a project an inherited
    # environment variable names, and so the assertion below addresses it.
    $env:COMPOSE_PROJECT_NAME = $project
    # Run the installer in a child host so a failure cannot take this script down.
    if (Get-Command pwsh -ErrorAction SilentlyContinue) {
        pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $bundle "install.ps1") -Offline
    } else {
        powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $bundle "install.ps1") -Offline
    }
    if ($LASTEXITCODE -ne 0) { throw "install.ps1 -Offline failed with exit $LASTEXITCODE" }
} finally {
    Remove-Item Env:\COMPOSE_PROJECT_NAME -ErrorAction SilentlyContinue
    Pop-Location
}

Write-Host "`n== asserting the installed stack =="
# `migrate` and `database-bootstrap` are one-shot jobs: they must exit 0, every
# long-running service must report healthy.
$oneShotServices = @("migrate", "database-bootstrap")
$deadline = (Get-Date).AddMinutes(6)
$healthy = $false
$finalState = @()
while ((Get-Date) -lt $deadline) {
    $finalState = @(docker compose -p $project ps --all --format "{{.Service}} {{.State}} {{.Health}} {{.ExitCode}}" 2>$null)
    $problems = @()
    foreach ($row in $finalState) {
        $parts = $row -split '\s+'
        $service = $parts[0]; $state = $parts[1]; $health = $parts[2]; $exitCode = $parts[3]
        if ($oneShotServices -contains $service) {
            if ($state -ne "exited" -or ($exitCode -and $exitCode -ne "0")) { $problems += "$service state=$state exit=$exitCode" }
            continue
        }
        if ($state -ne "running" -or $health -ne "healthy") { $problems += "$service state=$state health=$health" }
    }
    if ($finalState.Count -gt 0 -and $problems.Count -eq 0) { $healthy = $true; break }
    Start-Sleep -Seconds 10
}
$finalState = @(docker compose -p $project ps --all --format "{{.Service}} {{.State}} {{.Health}} {{.ExitCode}}" 2>$null)
$finalState | ForEach-Object { Write-Host "  $_" }

$gateway = try { (Invoke-WebRequest -Uri "http://127.0.0.1:$Port/gateway-health" -UseBasicParsing -TimeoutSec 20).StatusCode } catch { "error: $_" }
$health = try { (Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health" -UseBasicParsing -TimeoutSec 20).Content } catch { "error: $_" }
Write-Host "gateway-health: $gateway"
Write-Host "health: $health"

$evidence = [ordered]@{
    candidate_sha           = $sha
    version                 = $Version
    image_tag               = $tag
    migration_head          = $migrationHead
    backend_image           = $backendImage
    frontend_image          = $frontendImage
    images_tar_bytes        = $tarBytes
    images_tar_gz_bytes     = $gzBytes
    gzip_integrity_ok       = $gzipIntegrityOk
    gzip_uncompressed_bytes = $archiveBytes
    gzip_uncompressed_sha256 = $archiveHash
    install_offline_exit    = 0
    compose_project         = $project
    entry_port              = $Port
    all_services_healthy    = $healthy
    gateway_health          = "$gateway"
    health                  = "$health"
    compose_state           = @($finalState)
    checked_at              = (Get-Date).ToUniversalTime().ToString("o")
}
$evidencePath = Join-Path $work "stage15-install-evidence.json"
$evidence | ConvertTo-Json -Depth 5 | Set-Content -Path $evidencePath -Encoding utf8

Write-Host "`nevidence: $evidencePath"
if (-not $healthy) { throw "installed stack did not reach a healthy state" }
Write-Host "STAGE15 INSTALL SMOKE: PASS (local reproduction only)"
