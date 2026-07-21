# Start DramaForge P0 local stack: WSL Postgres + Windows API :8010 + Vite :5173
# Usage: powershell -ExecutionPolicy Bypass -File scripts/start_p0_stack.ps1
$ErrorActionPreference = "Continue"
$Repo = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path "$Repo\backend")) { $Repo = "D:\调研\dramaforge" }

Write-Host "==> Start WSL PostgreSQL"
wsl -d Ubuntu-24.04 -- bash -lc "sudo pg_ctlcluster 16 main start; PGPASSWORD=dramaforge psql -h 127.0.0.1 -U dramaforge -d dramaforge -c 'select 1' >/dev/null && echo PG_OK"

$pgOk = $false
for ($i = 0; $i -lt 15; $i++) {
  try {
    $c = New-Object System.Net.Sockets.TcpClient
    $c.Connect("127.0.0.1", 5432)
    $c.Close()
    $pgOk = $true
    break
  } catch {
    Start-Sleep -Seconds 1
  }
}
if (-not $pgOk) {
  Write-Host "ERROR: Windows cannot reach 127.0.0.1:5432 (WSL PG). Fix WSL port forward."
  exit 1
}
Write-Host "PG reachable from Windows"

# Free ports
foreach ($port in 8010) {
  Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
}
Start-Sleep -Seconds 1

Write-Host "==> Load .env and start API :8010 (development)"
Get-Content "$Repo\.env" -ErrorAction SilentlyContinue | ForEach-Object {
  if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
  if ($_ -match '^([^=]+)=(.*)$') {
    Set-Item -Path "env:$($matches[1].Trim())" -Value $matches[2].Trim()
  }
}
$env:APP_ENV = "development"
$env:DATABASE_URL = "postgresql+asyncpg://dramaforge:dramaforge@127.0.0.1:5432/dramaforge"
$env:DRAMA_FORCE_MEMORY_STORE = "1"
$env:PYTHONPATH = "$Repo\backend"
$env:CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"

$apiOut = "$Repo\.run\api.out.log"
$apiErr = "$Repo\.run\api.err.log"
New-Item -ItemType Directory -Force -Path "$Repo\.run" | Out-Null
$py = "$Repo\backend\.venv\Scripts\python.exe"
Start-Process -FilePath $py -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--port","8010" `
  -WorkingDirectory "$Repo\backend" -WindowStyle Hidden -RedirectStandardOutput $apiOut -RedirectStandardError $apiErr

$apiOk = $false
for ($i = 0; $i -lt 20; $i++) {
  try {
    $h = Invoke-RestMethod -Uri "http://127.0.0.1:8010/health" -TimeoutSec 2
    if ($h.status -eq "ok" -and $h.db -eq "up") { $apiOk = $true; break }
    if ($h.status -eq "ok" -and -not $h.db) { $apiOk = $true; break }
  } catch { Start-Sleep -Seconds 1 }
}
if ($apiOk) { Write-Host "API_OK db-up" } else {
  Write-Host "API may be degraded; see $apiErr"
  Get-Content $apiErr -Tail 20 -ErrorAction SilentlyContinue
}

$feListen = Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue
if (-not $feListen) {
  Write-Host "==> Start Vite :5173"
  Start-Process -FilePath "npm.cmd" -ArgumentList "run","dev","--","--host","127.0.0.1","--port","5173" `
    -WorkingDirectory "$Repo\frontend" -WindowStyle Hidden
} else {
  Write-Host "Vite already listening"
}

Start-Sleep -Seconds 2
try {
  $ph = Invoke-WebRequest "http://127.0.0.1:5173/health" -UseBasicParsing -TimeoutSec 3
  Write-Host "FE_PROXY $($ph.StatusCode) $($ph.Content)"
} catch {
  Write-Host "FE_PROXY_FAIL"
}

Write-Host "Open http://127.0.0.1:5173/"
