param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('log', 'tail', 'open')]
    [string]$Operation,

    [ValidateSet('STARTED', 'COMPLETED', 'FAILED', 'PAUSED', 'MERGED')]
    [string]$Status,
    [string]$TaskId,
    [string]$Agent,
    [string]$Summary,
    [string]$Branch,
    [string]$Worktree,
    [string]$ChangedFiles,
    [string]$Tests,
    [string]$Commit,
    [string]$Evidence,
    [string]$NextStep,
    [int]$Tail = 20
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $OutputEncoding

$RepoRoot = Split-Path -Parent $PSScriptRoot
$gitCommonDirectory = @(& git -C $RepoRoot rev-parse --path-format=absolute --git-common-dir 2>$null | Select-Object -First 1)
if ($gitCommonDirectory.Count -eq 1 -and -not [string]::IsNullOrWhiteSpace([string]$gitCommonDirectory[0])) {
    $primaryRepoRoot = Split-Path -Parent ([IO.Path]::GetFullPath([string]$gitCommonDirectory[0]))
    $ProgressPath = Join-Path $primaryRepoRoot '.agent-control\PROGRESS.jsonl'
}
else {
    $ProgressPath = Join-Path $PSScriptRoot 'PROGRESS.jsonl'
}
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Get-Now {
    return [DateTimeOffset]::Now.ToString('o')
}

function Redact-Text([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return $Value }

    $redacted = $Value
    $patterns = @(
        '(?i)github_pat_[A-Za-z0-9_]{20,}',
        '(?i)gh[pousr]_[A-Za-z0-9]{20,}',
        '(?i)sk-[A-Za-z0-9_-]{20,}',
        '(?i)AIza[0-9A-Za-z_-]{20,}',
        '(?i)(token|password|secret|api[_-]?key)\s*[=:]\s*[^\s;]+'
    )
    foreach ($pattern in $patterns) {
        $redacted = [regex]::Replace($redacted, $pattern, '[REDACTED]')
    }
    return $redacted
}

function Convert-ToList([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return @() }
    return @($Value -split ';' | ForEach-Object { (Redact-Text $_).Trim() } | Where-Object { $_ })
}

function Ensure-ProgressFile {
    if (-not (Test-Path -LiteralPath $PSScriptRoot -PathType Container)) {
        New-Item -ItemType Directory -Path $PSScriptRoot -Force | Out-Null
    }
    if (-not (Test-Path -LiteralPath $ProgressPath -PathType Leaf)) {
        [IO.File]::WriteAllText($ProgressPath, '', $Utf8NoBom)
    }
}

function Append-Line([string]$Line) {
    Ensure-ProgressFile
    $deadline = [DateTime]::UtcNow.AddSeconds(10)

    while ([DateTime]::UtcNow -lt $deadline) {
        $stream = $null
        $writer = $null
        try {
            $stream = [IO.File]::Open(
                $ProgressPath,
                [IO.FileMode]::OpenOrCreate,
                [IO.FileAccess]::Write,
                [IO.FileShare]::Read
            )
            $null = $stream.Seek(0, [IO.SeekOrigin]::End)
            $writer = New-Object IO.StreamWriter($stream, $Utf8NoBom)
            $writer.WriteLine($Line)
            $writer.Flush()
            return
        }
        catch [IO.IOException] {
            Start-Sleep -Milliseconds 100
        }
        finally {
            if ($null -ne $writer) { $writer.Dispose() }
            elseif ($null -ne $stream) { $stream.Dispose() }
        }
    }

    throw "Could not append to local progress ledger within 10 seconds: $ProgressPath"
}

function Read-Events {
    Ensure-ProgressFile
    $events = @()
    $lineNumber = 0
    foreach ($line in Get-Content -LiteralPath $ProgressPath -Encoding UTF8) {
        $lineNumber++
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        try {
            $events += $line | ConvertFrom-Json
        }
        catch {
            [Console]::Error.WriteLine("Skipped malformed JSONL record at line $lineNumber.")
        }
    }
    return @($events)
}

switch ($Operation) {
    'log' {
        if ([string]::IsNullOrWhiteSpace($Status)) { throw 'Status is required for log.' }
        if ([string]::IsNullOrWhiteSpace($TaskId)) { throw 'TaskId is required for log.' }
        if ([string]::IsNullOrWhiteSpace($Agent)) { throw 'Agent is required for log.' }
        if ([string]::IsNullOrWhiteSpace($Summary)) { throw 'Summary is required for log.' }

        $event = [ordered]@{
            schema_version = 1
            timestamp = Get-Now
            task_id = Redact-Text $TaskId
            agent = Redact-Text $Agent
            status = $Status
            summary = Redact-Text $Summary
            branch = Redact-Text $Branch
            worktree = Redact-Text $Worktree
            changed_files = @(Convert-ToList $ChangedFiles)
            tests = Redact-Text $Tests
            commit = Redact-Text $Commit
            evidence = @(Convert-ToList $Evidence)
            next_step = Redact-Text $NextStep
        }
        $line = $event | ConvertTo-Json -Compress -Depth 5
        Append-Line $line
        Write-Output $line
    }

    'tail' {
        if ($Tail -lt 0) { throw 'Tail must be zero or greater.' }
        Ensure-ProgressFile
        if ($Tail -gt 0) {
            Get-Content -LiteralPath $ProgressPath -Encoding UTF8 -Tail $Tail
        }
    }

    'open' {
        $latestByTask = @{}
        foreach ($event in Read-Events) {
            if ($null -ne $event.task_id) {
                $latestByTask[[string]$event.task_id] = $event
            }
        }
        $openTasks = @($latestByTask.Values |
            Where-Object { $_.status -in @('STARTED', 'PAUSED') } |
            Sort-Object timestamp)
        ConvertTo-Json -InputObject $openTasks -Depth 5
    }
}
