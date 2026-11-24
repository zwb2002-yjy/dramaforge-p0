# Shared ownership checks for disposable verification output, not a history ledger.
function Test-QualityOutputBoundary([string]$RepoRoot, [string]$Path) {
    $temporaryRoot = [IO.Path]::GetFullPath((Join-Path $RepoRoot 'tmp')).TrimEnd('\', '/')
    $candidate = [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    $comparison = if ([IO.Path]::DirectorySeparatorChar -eq '\') {
        [StringComparison]::OrdinalIgnoreCase
    } else { [StringComparison]::Ordinal }
    if (-not $candidate.StartsWith($temporaryRoot + [IO.Path]::DirectorySeparatorChar, $comparison)) {
        return $false
    }
    $ancestor = $candidate
    while ($ancestor) {
        if ((Test-Path -LiteralPath $ancestor) -and
            ((Get-Item -LiteralPath $ancestor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            return $false
        }
        $ancestor = Split-Path -Parent $ancestor
    }
    return $true
}

function New-QualityOutput([string]$Path) {
    if ((Test-Path -LiteralPath $Path) -and @(Get-ChildItem -LiteralPath $Path -Force).Count -gt 0) {
        throw 'Quality output directory is not empty; preserve it and select a fresh directory.'
    }
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
    $owner = [guid]::NewGuid().ToString('N')
    New-Item -ItemType File -Path (Join-Path $Path '.quality-owner') -Value $owner | Out-Null
    return $owner
}

function Clear-QualityOutput([string]$RepoRoot, [string]$Path, [string]$Owner) {
    if (-not (Test-QualityOutputBoundary $RepoRoot $Path)) {
        Write-Warning "Outputs retained outside the safe repository tmp boundary: $Path"
        return
    }
    $pending = [Collections.Generic.Stack[string]]::new()
    $pending.Push([IO.Path]::GetFullPath($Path))
    while ($pending.Count -gt 0) {
        foreach ($entry in Get-ChildItem -LiteralPath $pending.Pop() -Force) {
            if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Quality output contains a link; retained: $Path"
            }
            if ($entry.PSIsContainer) { $pending.Push($entry.FullName) }
        }
    }
    $marker = Join-Path $Path '.quality-owner'
    if (-not (Test-Path -LiteralPath $marker -PathType Leaf) -or
        (Get-Content -LiteralPath $marker -Raw) -cne $Owner) {
        throw "Quality output ownership changed; retained: $Path"
    }
    Remove-Item -LiteralPath ([IO.Path]::GetFullPath($Path)) -Recurse -Force
    Write-Output 'Quality checks passed; temporary outputs removed.'
}
