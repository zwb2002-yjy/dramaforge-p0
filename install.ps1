[CmdletBinding()]
param(
    [switch]$Offline
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $root

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker with Compose v2 is required.'
}
docker compose version | Out-Null

$releaseFile = Join-Path $root 'release.env'
if (-not (Test-Path -LiteralPath $releaseFile -PathType Leaf)) {
    throw 'release.env is missing. Use a complete DramaForge release bundle.'
}
$release = @{}
foreach ($line in Get-Content -LiteralPath $releaseFile -Encoding utf8) {
    if ($line -match '^([^#=]+)=(.*)$') { $release[$Matches[1]] = $Matches[2] }
}
foreach ($name in 'DRAMAFORGE_VERSION','DRAMAFORGE_SOURCE_COMMIT','DRAMAFORGE_BACKEND_IMAGE','DRAMAFORGE_FRONTEND_IMAGE') {
    if ([string]::IsNullOrWhiteSpace($release[$name])) { throw "release.env is missing $name" }
}
if ($release['DRAMAFORGE_SOURCE_COMMIT'] -notmatch '^[0-9a-f]{40}$') {
    throw 'release.env has an invalid source commit.'
}

if ($Offline) {
    $imageArchive = Join-Path $root 'images.tar'
    if (-not (Test-Path -LiteralPath $imageArchive -PathType Leaf)) {
        throw 'images.tar is missing. Use the complete offline release bundle.'
    }
    docker load --input $imageArchive
    if ($LASTEXITCODE -ne 0) { throw 'Failed to import offline release images.' }
}

$envFile = Join-Path $root '.env'
if (-not (Test-Path -LiteralPath $envFile)) {
    if (-not $Offline) { docker pull $release['DRAMAFORGE_BACKEND_IMAGE'] }
    $template = Get-Content -LiteralPath (Join-Path $root '.env.example') -Raw -Encoding utf8
    $rendered = $template | docker run --rm -i $release['DRAMAFORGE_BACKEND_IMAGE'] `
        python -m app.install_env `
        --version $release['DRAMAFORGE_VERSION'] `
        --source-commit $release['DRAMAFORGE_SOURCE_COMMIT'] `
        --backend-image $release['DRAMAFORGE_BACKEND_IMAGE'] `
        --frontend-image $release['DRAMAFORGE_FRONTEND_IMAGE']
    if ($LASTEXITCODE -ne 0) { throw 'Failed to initialize .env.' }
    [IO.File]::WriteAllText($envFile, ($rendered -join "`n") + "`n", [Text.UTF8Encoding]::new($false))
} else {
    $identity = @{
        DRAMAFORGE_VERSION = $release['DRAMAFORGE_VERSION']
        DRAMAFORGE_SOURCE_COMMIT = $release['DRAMAFORGE_SOURCE_COMMIT']
        DRAMAFORGE_BACKEND_IMAGE = $release['DRAMAFORGE_BACKEND_IMAGE']
        DRAMAFORGE_FRONTEND_IMAGE = $release['DRAMAFORGE_FRONTEND_IMAGE']
    }
    $lines = [Collections.Generic.List[string]]::new()
    foreach ($line in Get-Content -LiteralPath $envFile -Encoding utf8) { $lines.Add($line) }
    foreach ($name in $identity.Keys) {
        $found = $false
        for ($i = 0; $i -lt $lines.Count; $i++) {
            if ($lines[$i].StartsWith("$name=")) {
                $lines[$i] = "$name=$($identity[$name])"
                $found = $true
                break
            }
        }
        if (-not $found) { $lines.Add("$name=$($identity[$name])") }
    }
    [IO.File]::WriteAllText($envFile, ($lines -join "`n") + "`n", [Text.UTF8Encoding]::new($false))
    Write-Host 'Updated release identity; existing secrets and Provider settings were preserved.'
}

$composeArgs = @('--env-file', $envFile, '-f', 'docker-compose.yml')
if ($Offline) {
    $composeArgs += @('-f', 'docker-compose.offline.yml')
} else {
    docker compose @composeArgs pull
    if ($LASTEXITCODE -ne 0) { throw 'Failed to pull release images.' }
}
docker compose @composeArgs up -d --wait --no-build
if ($LASTEXITCODE -ne 0) { throw 'DramaForge failed to start.' }
$port = '8080'
foreach ($line in Get-Content -LiteralPath $envFile -Encoding utf8) {
    if ($line -match '^DRAMAFORGE_PORT=(.+)$') { $port = $Matches[1] }
}
Write-Host "DramaForge is ready at http://localhost:$port"
