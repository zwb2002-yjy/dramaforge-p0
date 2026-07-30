param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('create', 'check')]
    [string]$Operation,

    [Parameter(Mandatory = $true)]
    [string]$TaskId,

    [string]$OwnedPaths
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $OutputEncoding

$ScriptRepoRoot = Split-Path -Parent $PSScriptRoot
$gitCommonDirectory = (
    & git -C $ScriptRepoRoot rev-parse --path-format=absolute --git-common-dir
).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($gitCommonDirectory)) {
    throw 'Could not locate the repository Git common directory.'
}
$RepoRoot = Split-Path -Parent ([IO.Path]::GetFullPath($gitCommonDirectory))
$Validator = Join-Path $PSScriptRoot 'repo_guardrails.py'
$ProgressPath = Join-Path $RepoRoot '.agent-control\PROGRESS.jsonl'
$RootPython = Join-Path $RepoRoot 'backend\.venv\Scripts\python.exe'
$Python = if (Test-Path -LiteralPath $RootPython -PathType Leaf) {
    $RootPython
}
else {
    (Get-Command python -ErrorAction Stop).Source
}

$normalized = (& $Python $Validator normalize-task-id $TaskId).Trim()
if ($LASTEXITCODE -ne 0) {
    throw 'Invalid task id.'
}

if ($Operation -eq 'check') {
    & $Python $Validator validate-worktree --repo-root (Get-Location).Path --task-id $normalized
    if ($LASTEXITCODE -ne 0) {
        throw 'Current branch/worktree does not satisfy task isolation.'
    }
    if (-not [string]::IsNullOrWhiteSpace($OwnedPaths)) {
        & $Python $Validator check-ownership `
            --progress-path $ProgressPath `
            --task-id $normalized `
            --owned-paths $OwnedPaths
        if ($LASTEXITCODE -ne 0) {
            throw 'Owned paths overlap another active task.'
        }
    }
    return
}

if ([string]::IsNullOrWhiteSpace($OwnedPaths)) {
    throw 'OwnedPaths is required when creating a writable task worktree.'
}

$rootBranch = (& git -C $RepoRoot branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or $rootBranch -ne 'dev') {
    throw "Repository root worktree must be on dev; current branch is '$rootBranch'."
}
$rootChanges = @(& git -C $RepoRoot status --porcelain)
if ($LASTEXITCODE -ne 0 -or $rootChanges.Count -gt 0) {
    throw 'Repository root dev worktree must be clean before creating an isolated task.'
}

& $Python $Validator check-ownership `
    --progress-path $ProgressPath `
    --task-id $normalized `
    --owned-paths $OwnedPaths
if ($LASTEXITCODE -ne 0) {
    throw 'Owned paths overlap another active task.'
}

$branch = "agent/$normalized"
$worktree = Join-Path $RepoRoot ".worktrees\$normalized"
if (Test-Path -LiteralPath $worktree) {
    throw "Worktree already exists: $worktree"
}
$null = & git -C $RepoRoot show-ref --verify --quiet "refs/heads/$branch"
if ($LASTEXITCODE -eq 0) {
    throw "Branch already exists: $branch"
}

& git -C $RepoRoot worktree add $worktree -b $branch dev
if ($LASTEXITCODE -ne 0) {
    throw 'git worktree add failed.'
}

Write-Output "Created $branch at $worktree"
