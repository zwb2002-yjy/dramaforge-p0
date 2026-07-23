param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
& git -C $RepoRoot config core.hooksPath .githooks
if ($LASTEXITCODE -ne 0) {
    throw 'Failed to configure core.hooksPath.'
}

$configured = (& git -C $RepoRoot config --get core.hooksPath).Trim()
if ($configured -ne '.githooks') {
    throw "Unexpected core.hooksPath: $configured"
}

Write-Output 'Git hooks installed: core.hooksPath=.githooks'
