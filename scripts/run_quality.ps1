# Compatibility entrypoint: all project quality checks run in Docker.
$ErrorActionPreference = "Stop"
$QualityScript = Join-Path $PSScriptRoot "run_quality_in_docker.ps1"
& $QualityScript @args
exit $LASTEXITCODE
