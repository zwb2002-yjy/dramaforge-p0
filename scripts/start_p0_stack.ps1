# DramaForge local stack launcher.
#
# The default keeps PostgreSQL and the API in WSL, so database traffic never
# crosses the unstable Windows-to-WSL localhost forwarding boundary.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\start_p0_stack.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\start_p0_stack.ps1 -Action Status
#   powershell -ExecutionPolicy Bypass -File scripts\start_p0_stack.ps1 -Action Stop
#   powershell -ExecutionPolicy Bypass -File scripts\start_p0_stack.ps1 -Mode WindowsApi -DbHost WslIp
#
# Keep this file ASCII-only. Windows PowerShell 5.1 can misread UTF-8 scripts
# without a BOM, which previously corrupted a hard-coded path containing
# non-ASCII characters and prevented the WSL API from starting.

param(
  [ValidateSet("Start", "Status", "Stop")]
  [string]$Action = "Start",
  [ValidateSet("WslApi", "WindowsApi")]
  [string]$Mode = "WslApi",
  [ValidateSet("Localhost", "WslIp")]
  [string]$DbHost = "Localhost",
  [string]$WslDistro = "Ubuntu-24.04",
  [int]$ApiPort = 8010,
  [int]$FePort = 5173,
  [switch]$SkipFrontend
)

$ErrorActionPreference = "Stop"
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RunDir = Join-Path $Repo ".run"
New-Item -ItemType Directory -Force -Path $RunDir | Out-Null

function Get-WslIp {
  $raw = (& wsl.exe -d $WslDistro -- hostname -I 2>$null | Select-Object -First 1)
  if (-not $raw) {
    return $null
  }
  return ($raw.ToString().Trim() -split "\s+")[0]
}

function Invoke-WslStack([string]$WslAction) {
  Push-Location $Repo
  try {
    # Formal path: full PG+Redis+MinIO+API+Workers+dispatcher (no FORCE_MEMORY).
    # WSL converts the current Windows directory itself (ASCII-safe).
    & wsl.exe -d $WslDistro -- bash scripts/start_p0_wsl_stack.sh $WslAction $ApiPort $FePort |
      ForEach-Object { Write-Host $_ }
    return [int]$LASTEXITCODE
  } finally {
    Pop-Location
  }
}

function Get-Health([string]$Url) {
  try {
    $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
    return @{
      Code = [int]$response.StatusCode
      Body = $response.Content | ConvertFrom-Json
    }
  } catch {
    return $null
  }
}

function Wait-Health([string]$Url, [int]$Tries = 20) {
  for ($i = 0; $i -lt $Tries; $i++) {
    $result = Get-Health $Url
    if ($result -and $result.Code -eq 200 -and $result.Body.status -eq "ok" -and $result.Body.db -eq "up") {
      return $result
    }
    Start-Sleep -Seconds 1
  }
  return $null
}

function Get-ListeningProcess([int]$Port) {
  $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1
  if (-not $listener) {
    return $null
  }
  return Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
}

function Test-OwnedVite([object]$Process) {
  if (-not $Process) {
    return $false
  }
  return $Process.Name -eq "node.exe" -and
    $Process.CommandLine -match [regex]::Escape((Join-Path $Repo "frontend")) -and
    $Process.CommandLine -match "vite"
}

function Test-OwnedWindowsApi([object]$Process) {
  if (-not $Process) {
    return $false
  }
  return $Process.Name -match "^python(?:\.exe)?$" -and
    $Process.CommandLine -match [regex]::Escape((Join-Path $Repo "backend")) -and
    $Process.CommandLine -match "uvicorn"
}

function Stop-OwnedVite {
  $process = Get-ListeningProcess $FePort
  if (-not $process) {
    return
  }
  if (-not (Test-OwnedVite $process)) {
    throw "Port $FePort is owned by $($process.Name) pid=$($process.ProcessId), not this repository's Vite process."
  }
  Stop-Process -Id $process.ProcessId -Force
  Start-Sleep -Milliseconds 500
}

function Stop-OwnedWindowsApi {
  $process = Get-ListeningProcess $ApiPort
  if (-not $process) {
    return
  }
  if (-not (Test-OwnedWindowsApi $process)) {
    throw "Port $ApiPort is owned by $($process.Name) pid=$($process.ProcessId), not this repository's Windows API process."
  }
  Stop-Process -Id $process.ProcessId -Force
  Start-Sleep -Milliseconds 500
}

function Load-ProjectEnv {
  $envFile = Join-Path $Repo ".env"
  if (-not (Test-Path $envFile)) {
    return
  }
  Get-Content -LiteralPath $envFile | ForEach-Object {
    if ($_ -match "^\s*(#|$)") {
      return
    }
    if ($_ -match "^(?<Key>[A-Za-z_][A-Za-z0-9_]*)=(?<Value>.*)$") {
      Set-Item -Path "Env:$($Matches.Key)" -Value $Matches.Value
    }
  }
}

function Start-Frontend([string]$ApiTarget) {
  if ($SkipFrontend) {
    return
  }

  $existing = Get-ListeningProcess $FePort
  if ($existing) {
    $proxyHealth = Get-Health "http://127.0.0.1:$FePort/health"
    if ($proxyHealth -and $proxyHealth.Code -eq 200 -and $proxyHealth.Body.db -eq "up") {
      Write-Host "VITE_READY port=$FePort target=existing"
      return
    }
    Stop-OwnedVite
  }

  $env:DRAMAFORGE_API_URL = $ApiTarget
  $feOut = Join-Path $RunDir "vite.out.log"
  $feErr = Join-Path $RunDir "vite.err.log"
  Start-Process -FilePath "npm.cmd" -ArgumentList "run", "dev", "--", "--host", "127.0.0.1", "--port", "$FePort", "--strictPort" `
    -WorkingDirectory (Join-Path $Repo "frontend") -WindowStyle Hidden `
    -RedirectStandardOutput $feOut -RedirectStandardError $feErr | Out-Null

  $proxyHealth = Wait-Health "http://127.0.0.1:$FePort/health" 15
  if (-not $proxyHealth) {
    throw "Vite started but its /health proxy is not ready. See $feOut and $feErr."
  }
  Write-Host "VITE_READY port=$FePort target=$ApiTarget"
}

function Start-WindowsApi {
  $existing = Get-ListeningProcess $ApiPort
  if ($existing) {
    $existingHealth = Get-Health "http://127.0.0.1:$ApiPort/health"
    if ((Test-OwnedWindowsApi $existing) -and $existingHealth -and $existingHealth.Code -eq 200 -and $existingHealth.Body.db -eq "up") {
      Write-Host "API_READY port=$ApiPort target=existing"
      return
    }
    Stop-OwnedWindowsApi
  }

  $code = Invoke-WslStack "prepare"
  if ($code -ne 0) {
    throw "WSL PostgreSQL preparation failed. Check the WSL database and migrations before starting the Windows API."
  }

  $dbHostName = "127.0.0.1"
  if ($DbHost -eq "WslIp") {
    $dbHostName = Get-WslIp
    if (-not $dbHostName) {
      throw "Cannot resolve the WSL IP address."
    }
  }

  Load-ProjectEnv
  $env:APP_ENV = "development"
  $env:DATABASE_URL = "postgresql+asyncpg://dramaforge:dramaforge@${dbHostName}:5432/dramaforge"
  $env:DRAMA_FORCE_MEMORY_STORE = "1"
  $env:PYTHONPATH = (Join-Path $Repo "backend")
  $env:CORS_ORIGINS = "http://localhost:$FePort,http://127.0.0.1:$FePort"

  $apiOut = Join-Path $RunDir "api.out.log"
  $apiErr = Join-Path $RunDir "api.err.log"
  $python = Join-Path $Repo "backend\.venv\Scripts\python.exe"
  if (-not (Test-Path $python)) {
    throw "Missing Windows virtual environment: $python"
  }

  Start-Process -FilePath $python -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$ApiPort" `
    -WorkingDirectory (Join-Path $Repo "backend") -WindowStyle Hidden `
    -RedirectStandardOutput $apiOut -RedirectStandardError $apiErr | Out-Null
}

if ($Action -eq "Stop") {
  if ($Mode -eq "WslApi") {
    $code = Invoke-WslStack "stop"
    if ($code -ne 0) {
      exit $code
    }
  } else {
    Stop-OwnedWindowsApi
  }
  if (-not $SkipFrontend) {
    Stop-OwnedVite
  }
  Write-Host "STACK_STOPPED"
  exit 0
}

if ($Action -eq "Status") {
  if ($Mode -eq "WslApi") {
    $code = Invoke-WslStack "status"
    if ($code -ne 0) {
      exit $code
    }
  }
  $api = Get-Health "http://127.0.0.1:$ApiPort/health"
  $fe = if ($SkipFrontend) { $null } else { Get-Health "http://127.0.0.1:$FePort/health" }
  if (-not $api -or $api.Code -ne 200 -or $api.Body.db -ne "up") {
    Write-Host "API_NOT_READY"
    exit 1
  }
  if (-not $SkipFrontend -and (-not $fe -or $fe.Code -ne 200 -or $fe.Body.db -ne "up")) {
    Write-Host "VITE_PROXY_NOT_READY"
    exit 1
  }
  Write-Host "STACK_READY api=$ApiPort frontend=$FePort"
  exit 0
}

Write-Host "STACK_START mode=$Mode distro=$WslDistro"
if ($Mode -eq "WslApi") {
  $code = Invoke-WslStack "start"
  if ($code -ne 0) {
    throw "WSL API start failed. Run with -Action Status or inspect the WSL journal."
  }

  $apiTarget = "http://127.0.0.1:$ApiPort"
  $apiHealth = Wait-Health "$apiTarget/health" 10
  if (-not $apiHealth) {
    $wslIp = Get-WslIp
    if ($wslIp) {
      $apiTarget = "http://${wslIp}:$ApiPort"
      $apiHealth = Wait-Health "$apiTarget/health" 10
    }
  }
  if (-not $apiHealth) {
    throw "WSL API is healthy inside WSL but Windows cannot reach it. Check WSL networking and use the WSL IP shown by 'wsl -d $WslDistro -- hostname -I'."
  }
} else {
  Start-WindowsApi
  $apiTarget = "http://127.0.0.1:$ApiPort"
  $apiHealth = Wait-Health "$apiTarget/health" 20
  if (-not $apiHealth) {
    throw "Windows API did not become ready. See $(Join-Path $RunDir 'api.err.log')."
  }
}

Start-Frontend $apiTarget
Write-Host "STACK_READY api=$apiTarget frontend=http://127.0.0.1:$FePort"
