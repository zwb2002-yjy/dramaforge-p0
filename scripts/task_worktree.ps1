param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('create', 'check')]
    [string]$Operation,
    [string]$TaskId
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
if ($Operation -eq 'check') {
    # Report actual Git state without imposing a branch/path or clean-root policy.
    git -C $repo worktree list
    if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect worktrees.' }
    return
}
$normalized = $TaskId.Trim().ToLowerInvariant()
if ($normalized -notmatch '^[a-z0-9]+(?:[._-][a-z0-9]+)*$') { throw 'Invalid task ID.' }
$common = (git -C $repo rev-parse --path-format=absolute --git-common-dir).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Cannot locate repository.' }
$primary = Split-Path -Parent ([IO.Path]::GetFullPath($common))
$worktree = Join-Path $primary ".worktrees/$normalized"
$branch = "codex/$normalized"
if (Test-Path -LiteralPath $worktree) { throw "Worktree already exists: $worktree" }
git -C $repo show-ref --verify --quiet "refs/heads/$branch"
if ($LASTEXITCODE -eq 0) { throw "Branch already exists: $branch" }
# Start from the dev commit without staging, committing or changing its dirty worktree.
git -C $repo worktree add -b $branch $worktree dev
if ($LASTEXITCODE -ne 0) { throw 'Worktree creation failed.' }
Write-Output "Created $branch at $worktree. Coordinate write ownership in the existing task."
