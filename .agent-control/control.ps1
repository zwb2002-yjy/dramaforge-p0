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
    [string]$OwnedPaths,
    [switch]$ReadOnly,
    [string]$ApprovedBy,
    [int]$PrNumber = 0,
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
    $progressDirectory = Split-Path -Parent $ProgressPath
    if (-not (Test-Path -LiteralPath $progressDirectory -PathType Container)) {
        New-Item -ItemType Directory -Path $progressDirectory -Force | Out-Null
    }
    if (-not (Test-Path -LiteralPath $ProgressPath -PathType Leaf)) {
        [IO.File]::WriteAllText($ProgressPath, '', $Utf8NoBom)
    }
}

function Append-ValidatedEvent(
    [Collections.IDictionary]$Candidate,
    [string]$EventAgent,
    [string]$EventSummary,
    [string]$EventChangedFiles,
    [string]$EventTests,
    [string]$EventCommit,
    [string]$EventEvidence,
    [string]$EventNextStep
) {
    Ensure-ProgressFile
    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    $validator = Join-Path $RepoRoot 'scripts\repo_guardrails.py'
    if (-not (Test-Path -LiteralPath $validator -PathType Leaf)) {
        throw "Repository validator not found: $validator"
    }
    $candidateJson = $Candidate | ConvertTo-Json -Compress -Depth 5
    $candidateBase64 = [Convert]::ToBase64String(
        [Text.Encoding]::UTF8.GetBytes($candidateJson)
    )
    $python = Get-PythonExecutable

    while ([DateTime]::UtcNow -lt $deadline) {
        $stream = $null
        $writer = $null
        $snapshotPath = $null
        try {
            $stream = [IO.File]::Open(
                $ProgressPath,
                [IO.FileMode]::OpenOrCreate,
                [IO.FileAccess]::ReadWrite,
                [IO.FileShare]::None
            )
            $snapshotPath = "$ProgressPath.$PID.$([guid]::NewGuid().ToString('N')).snapshot"
            $snapshot = [IO.File]::Open(
                $snapshotPath,
                [IO.FileMode]::CreateNew,
                [IO.FileAccess]::Write,
                [IO.FileShare]::None
            )
            try {
                $stream.Position = 0
                $stream.CopyTo($snapshot)
                $snapshot.Flush($true)
            }
            finally {
                $snapshot.Dispose()
            }

            $validatedJson = & $python $validator validate-event `
                --repo-root $RepoRoot `
                --progress-path $snapshotPath `
                --event-base64 $candidateBase64
            if ($LASTEXITCODE -ne 0) {
                throw 'Repository workflow event rejected.'
            }
            $validated = $validatedJson | ConvertFrom-Json
            $event = [ordered]@{
                schema_version = 2
                timestamp = Get-Now
                task_id = [string]$validated.task_id
                agent = Redact-Text $EventAgent
                status = [string]$validated.status
                summary = Redact-Text $EventSummary
                branch = [string]$validated.branch
                worktree = [string]$validated.worktree
                owned_paths = @($validated.owned_paths)
                read_only = [bool]$validated.read_only
                approved_by = [string]$validated.approved_by
                pr_number = [int]$validated.pr_number
                changed_files = @($validated.changed_files)
                tests = Redact-Text $EventTests
                commit = Redact-Text ([string]$validated.commit)
                merge_commit = Redact-Text ([string]$validated.merge_commit)
                evidence = @(Convert-ToList $EventEvidence)
                next_step = Redact-Text $EventNextStep
            }
            $line = $event | ConvertTo-Json -Compress -Depth 5
            $null = $stream.Seek(0, [IO.SeekOrigin]::End)
            $writer = [IO.StreamWriter]::new($stream, $Utf8NoBom, 1024, $true)
            $writer.WriteLine($line)
            $writer.Flush()
            $stream.Flush($true)
            Write-Output $line
            return
        }
        catch [IO.IOException] {
            Start-Sleep -Milliseconds 100
        }
        finally {
            if ($null -ne $writer) { $writer.Dispose() }
            if ($null -ne $stream) { $stream.Dispose() }
            if (
                $null -ne $snapshotPath -and
                (Test-Path -LiteralPath $snapshotPath -PathType Leaf)
            ) {
                Remove-Item -LiteralPath $snapshotPath -Force
            }
        }
    }

    throw "Could not lock and append to local progress ledger within 10 seconds: $ProgressPath"
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

function Get-PythonExecutable {
    $rootVenv = Join-Path $primaryRepoRoot 'backend\.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $rootVenv -PathType Leaf) {
        return $rootVenv
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($null -ne $python) {
        return $python.Source
    }
    throw 'Python 3.12 is required to validate repository workflow events.'
}

switch ($Operation) {
    'log' {
        if ([string]::IsNullOrWhiteSpace($Status)) { throw 'Status is required for log.' }
        if ([string]::IsNullOrWhiteSpace($TaskId)) { throw 'TaskId is required for log.' }
        if ([string]::IsNullOrWhiteSpace($Agent)) { throw 'Agent is required for log.' }
        if ([string]::IsNullOrWhiteSpace($Summary)) { throw 'Summary is required for log.' }

        $candidate = [ordered]@{
            task_id = Redact-Text $TaskId
            status = $Status
            branch = Redact-Text $Branch
            worktree = Redact-Text $Worktree
            owned_paths = @(Convert-ToList $OwnedPaths)
            read_only = if ($PSBoundParameters.ContainsKey('ReadOnly')) {
                [bool]$ReadOnly.IsPresent
            }
            else {
                $null
            }
            approved_by = Redact-Text $ApprovedBy
            pr_number = $PrNumber
            changed_files = @(Convert-ToList $ChangedFiles)
            commit = Redact-Text $Commit
        }
        Append-ValidatedEvent `
            -Candidate $candidate `
            -EventAgent $Agent `
            -EventSummary $Summary `
            -EventChangedFiles $ChangedFiles `
            -EventTests $Tests `
            -EventCommit $Commit `
            -EventEvidence $Evidence `
            -EventNextStep $NextStep
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
