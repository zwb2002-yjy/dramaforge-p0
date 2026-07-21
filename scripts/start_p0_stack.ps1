# DramaForge P0 local stack — bypass flaky Windows↔WSL Postgres localhost forward.
#
# Default (recommended): PostgreSQL + API both inside WSL (same loopback).
# Frontend stays on Windows :5173 and proxies /api + /health → 127.0.0.1:8010.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/start_p0_stack.ps1
#   powershell -ExecutionPolicy Bypass -File scripts/start_p0_stack.ps1 -Mode WslApi
#   powershell -ExecutionPolicy Bypass -File scripts/start_p0_stack.ps1 -Mode WindowsApi
#   powershell -ExecutionPolicy Bypass -File scripts/start_p0_stack.ps1 -Mode WindowsApi -DbHost WslIp
#
# Why: Windows processes talking to WSL Postgres via 127.0.0.1:5432 break when
# localhost forwarding / NAT mode drops. Running API in WSL removes that hop.

param(
  [ValidateSet("WslApi", "WindowsApi")]
  [string]$Mode = "WslApi",
  [ValidateSet("Localhost", "WslIp")]
  [string]$DbHost = "Localhost",
  [string]$WslDistro = "Ubuntu-24.04",
  [int]$ApiPort = 8010,
  [int]$FePort = 5173
)

$ErrorActionPreference = "Continue"
$Repo = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path "$Repo\backend")) { $Repo = "D:\调研\dramaforge" }
New-Item -ItemType Directory -Force -Path "$Repo\.run" | Out-Null

function Get-WslIp {
  $raw = (wsl -d $WslDistro -- hostname -I 2>$null)
  if (-not $raw) { return $null }
  return ($raw.ToString().Trim() -split "\s+")[0]
}

function Test-Tcp([string]$HostName, [int]$Port, [int]$TimeoutMs = 1500) {
  try {
    $c = New-Object System.Net.Sockets.TcpClient
    $iar = $c.BeginConnect($HostName, $Port, $null, $null)
    if (-not $iar.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) {
      $c.Close()
      return $false
    }
    $c.EndConnect($iar)
    $c.Close()
    return $true
  } catch {
    return $false
  }
}

function Wait-Health([string]$Url, [int]$Tries = 25) {
  for ($i = 0; $i -lt $Tries; $i++) {
    try {
      $h = Invoke-RestMethod -Uri $Url -TimeoutSec 2
      if ($h.status -eq "ok" -and ($h.db -eq "up" -or -not $h.db)) {
        return $h
      }
      Write-Host "  wait health status=$($h.status) db=$($h.db)"
    } catch {
      # retry
    }
    Start-Sleep -Seconds 1
  }
  return $null
}

Write-Host "==> Mode=$Mode DbHost=$DbHost"
Write-Host "==> Start WSL PostgreSQL ($WslDistro)"
wsl -d $WslDistro -- bash -lc "sudo pg_ctlcluster 16 main start >/dev/null 2>&1; PGPASSWORD=dramaforge psql -h 127.0.0.1 -U dramaforge -d dramaforge -tAc 'select 1' 2>/dev/null | grep -q 1 && echo PG_OK || echo PG_FAIL"

# Free Windows listeners that would steal :8010 from WSL published port
foreach ($port in @($ApiPort)) {
  Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object {
      $p = $_.OwningProcess
      Write-Host "  free Windows port $port pid=$p"
      Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
    }
}
Start-Sleep -Seconds 1

if ($Mode -eq "WslApi") {
  Write-Host "==> Start API inside WSL (DB via 127.0.0.1 — no cross-boundary hop)"
  $sh = "/mnt/d/调研/dramaforge/scripts/start_api_wsl_stable.sh"
  # Prefer path relative to this repo mount if available
  wsl -d $WslDistro -- bash -lc "if [ -f '$sh' ]; then bash '$sh'; else bash /mnt/d/调研/dramaforge/scripts/start_api_wsl_stable.sh; fi"
} else {
  # Windows API — choose a DB host that is actually reachable
  $dbHostName = "127.0.0.1"
  if ($DbHost -eq "WslIp") {
    $wslip = Get-WslIp
    if (-not $wslip) {
      Write-Host "ERROR: cannot resolve WSL IP"
      exit 1
    }
    $dbHostName = $wslip
    Write-Host "  DATABASE host = WSL eth IP $dbHostName (bypasses localhost forward)"
  } else {
    Write-Host "  DATABASE host = 127.0.0.1 (depends on WSL localhost forward — flaky)"
  }

  if (-not (Test-Tcp $dbHostName 5432)) {
    Write-Host "ERROR: cannot TCP-connect ${dbHostName}:5432"
    Write-Host "  Try: -Mode WslApi   OR   -Mode WindowsApi -DbHost WslIp"
    exit 1
  }

  Write-Host "==> Start Windows API :$ApiPort → postgres@$dbHostName"
  Get-Content "$Repo\.env" -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
    if ($_ -match '^([^=]+)=(.*)$') {
      Set-Item -Path "env:$($matches[1].Trim())" -Value $matches[2].Trim()
    }
  }
  $env:APP_ENV = "development"
  $env:DATABASE_URL = "postgresql+asyncpg://dramaforge:dramaforge@${dbHostName}:5432/dramaforge"
  $env:DRAMA_FORCE_MEMORY_STORE = "1"
  $env:PYTHONPATH = "$Repo\backend"
  $env:CORS_ORIGINS = "http://localhost:$FePort,http://127.0.0.1:$FePort"

  $apiOut = "$Repo\.run\api.out.log"
  $apiErr = "$Repo\.run\api.err.log"
  $py = "$Repo\backend\.venv\Scripts\python.exe"
  Start-Process -FilePath $py -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--port","$ApiPort" `
    -WorkingDirectory "$Repo\backend" -WindowStyle Hidden `
    -RedirectStandardOutput $apiOut -RedirectStandardError $apiErr
}

$health = Wait-Health "http://127.0.0.1:$ApiPort/health"
if ($health) {
  Write-Host "API_OK status=$($health.status) db=$($health.db) env=$($health.env)"
} else {
  Write-Host "API_NOT_READY on 127.0.0.1:$ApiPort"
  # Secondary probe via WSL IP (when localhost forward to WSL is broken but eth works)
  $wslip = Get-WslIp
  if ($wslip) {
    $alt = Wait-Health "http://${wslip}:$ApiPort/health" 5
    if ($alt) {
      Write-Host "API_OK via WSL IP $wslip (localhost forward broken)"
      Write-Host "  Fix Vite proxy target to http://${wslip}:$ApiPort  OR enable WSL mirrored networking"
      Write-Host "  See docs/runbooks/local-stack-bypass.md"
    } else {
      Write-Host "  Also failed via $wslip — check WSL log: ~/.cache/dramaforge-api.log"
    }
  }
}

$feListen = Get-NetTCPConnection -LocalPort $FePort -State Listen -ErrorAction SilentlyContinue
if (-not $feListen) {
  Write-Host "==> Start Vite :$FePort"
  Start-Process -FilePath "npm.cmd" -ArgumentList "run","dev","--","--host","127.0.0.1","--port","$FePort","--strictPort" `
    -WorkingDirectory "$Repo\frontend" -WindowStyle Hidden
} else {
  Write-Host "Vite already listening on :$FePort"
}

Start-Sleep -Seconds 2
try {
  $ph = Invoke-WebRequest "http://127.0.0.1:$FePort/health" -UseBasicParsing -TimeoutSec 3
  Write-Host "FE_PROXY $($ph.StatusCode) $($ph.Content)"
} catch {
  Write-Host "FE_PROXY_FAIL (API may still be up; open FE anyway)"
}

Write-Host ""
Write-Host "Open http://127.0.0.1:$FePort/"
Write-Host "Health http://127.0.0.1:$ApiPort/health  (must status=ok and db=up)"
Write-Host "Preferred stack: -Mode WslApi  (API+PG same machine)"
