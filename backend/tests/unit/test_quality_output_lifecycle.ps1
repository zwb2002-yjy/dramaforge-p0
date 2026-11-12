param([string]$Scenario, [string]$ScenarioRoot)

$ErrorActionPreference = 'Stop'

if ($Scenario) {
    # Child process: execute the real entrypoint with synthetic Docker responses.
    $env:GITHUB_OUTPUT = $null
    $env:COMPOSE_PROJECT_NAME = 'df-quality-lifecycle-test'
    $env:QUALITY_BACKEND_IMAGE = 'prior-backend'
    $env:QUALITY_FRONTEND_IMAGE = 'prior-frontend'
    $env:QUALITY_CONTRACT_DIR = Join-Path $ScenarioRoot 'tmp/output'
    $global:QualityLifecycleOutputPath = $env:QUALITY_CONTRACT_DIR
    $global:QualityLifecycleCallsPath = Join-Path $ScenarioRoot 'calls.txt'
    $global:QualityLifecycleOutsidePath = Join-Path $ScenarioRoot 'outside'
    New-Item -ItemType Directory -Path $global:QualityLifecycleOutsidePath | Out-Null
    Set-Content -LiteralPath (Join-Path $global:QualityLifecycleOutsidePath 'sentinel') -Value 'keep'
    if ($Scenario -eq 'external') {
        $env:QUALITY_CONTRACT_DIR = Join-Path $global:QualityLifecycleOutsidePath 'output'
        $global:QualityLifecycleOutputPath = $env:QUALITY_CONTRACT_DIR
    }
    if ($Scenario -eq 'parent-link') {
        $linkType = if ([IO.Path]::DirectorySeparatorChar -eq '\') { 'Junction' } else { 'SymbolicLink' }
        New-Item -ItemType $linkType -Path (Join-Path $ScenarioRoot 'tmp') -Target $global:QualityLifecycleOutsidePath | Out-Null
    }
    if ($Scenario -eq 'nonempty') {
        New-Item -ItemType Directory -Path $global:QualityLifecycleOutputPath -Force | Out-Null
        Set-Content -LiteralPath (Join-Path $global:QualityLifecycleOutputPath 'sentinel') -Value 'keep'
    }
    $global:QualityLifecycleScenario = $Scenario
    function docker {
        $command = $args -join ' '
        Add-Content -LiteralPath $global:QualityLifecycleCallsPath -Value $command
        $global:LASTEXITCODE = 0
        if ($args[0] -eq 'inspect') { 'healthy'; return }
        if ($command -match ' ps -q ') { 'synthetic-container'; return }
        if ($args[0] -eq 'build') {
            $iidIndex = [Array]::IndexOf($args, '--iidfile')
            if ($iidIndex -lt 0) { throw 'A build must return its own immutable image ID.' }
            $digit = if ($command -match 'backend/Dockerfile') { 'a' } else { 'b' }
            $identity = if ($global:QualityLifecycleScenario -eq 'invalid-id') { 'not-an-image' } else { 'sha256:' + ($digit * 64) }
            Set-Content -LiteralPath $args[$iidIndex + 1] -Value $identity -NoNewline
            Set-Content -LiteralPath (Join-Path $global:QualityLifecycleOutputPath 'openapi.json') -Value '{}'
            if ($global:QualityLifecycleScenario -eq 'owner-changed') {
                Set-Content -LiteralPath (Join-Path $global:QualityLifecycleOutputPath '.quality-owner') -Value 'other-run'
            }
            if ($global:QualityLifecycleScenario -eq 'child-link' -and
                -not (Test-Path -LiteralPath (Join-Path $global:QualityLifecycleOutputPath 'linked'))) {
                $linkType = if ([IO.Path]::DirectorySeparatorChar -eq '\') { 'Junction' } else { 'SymbolicLink' }
                New-Item -ItemType $linkType -Path (Join-Path $global:QualityLifecycleOutputPath 'linked') -Target $global:QualityLifecycleOutsidePath | Out-Null
            }
            if ($global:QualityLifecycleScenario -eq 'failed') { $global:LASTEXITCODE = 17 }
        }
        # Mutable tags could now refer to another build; every stage must use our IDs.
        if ($args[0] -eq 'compose' -and $command -match ' (up|run) ') {
            if ($env:QUALITY_BACKEND_IMAGE -cne ('sha256:' + ('a' * 64)) -or
                $env:QUALITY_FRONTEND_IMAGE -cne ('sha256:' + ('b' * 64))) {
                throw 'A runtime stage resolved shared mutable tags instead of build IDs.'
            }
        }
        if ($command -match ' down ' -and $global:QualityLifecycleScenario -eq 'cleanup-failed') {
            $global:LASTEXITCODE = 19
        }
    }
    if ($Scenario.StartsWith('offline-')) {
        . (Join-Path $ScenarioRoot 'scripts/quality_output.ps1')
        $repo = $ScenarioRoot
        $work = $global:QualityLifecycleOutputPath
        $bundle = Join-Path $work 'bundle'
        $outputOwner = New-QualityOutput $work
        New-Item -ItemType Directory -Path $bundle | Out-Null
        Set-Content -LiteralPath (Join-Path $bundle 'synthetic-archive') -Value 'fixture'
        $PreviousProject = $env:COMPOSE_PROJECT_NAME
        $project = 'dramaforge-install-synthetic'
        $OwnStack = $true
        $OwnProbe = $false
        $Verified = $Scenario -ne 'offline-failed'
        $KeepArtifacts = $Scenario -eq 'offline-keep'
        $tokens = $null
        $parseErrors = $null
        $tree = [Management.Automation.Language.Parser]::ParseFile(
            (Join-Path $ScenarioRoot 'scripts/verify_offline_install.ps1'), [ref]$tokens, [ref]$parseErrors)
        if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
        $cleanup = @($tree.EndBlock.Statements | Where-Object { $_ -is [Management.Automation.Language.TryStatementAst] })[0].Finally
        # Exercise the installer's actual cleanup block without building multi-GB packages.
        $cleanupText = $cleanup.Extent.Text
        . ([scriptblock]::Create($cleanupText.Substring(1, $cleanupText.Length - 2)))
        exit $LASTEXITCODE
    }
    $runner = Join-Path $ScenarioRoot 'scripts/run_quality_in_docker.ps1'
    if ($Scenario -eq 'keep') { & $runner -Stage Full -KeepArtifacts }
    else { & $runner -Stage Full }
    if ($env:QUALITY_BACKEND_IMAGE -ne 'prior-backend' -or $env:QUALITY_FRONTEND_IMAGE -ne 'prior-frontend') {
        throw 'Caller image configuration was not restored.'
    }
    exit $LASTEXITCODE
}

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('df-quality-lifecycle-' + [guid]::NewGuid().ToString('N'))
$shellName = if ([IO.Path]::DirectorySeparatorChar -eq '\') { 'pwsh.exe' } else { 'pwsh' }
$shellPath = Join-Path $PSHOME $shellName
if (-not (Test-Path -LiteralPath $shellPath) -and [IO.Path]::DirectorySeparatorChar -eq '\') {
    # Windows PowerShell host without pwsh: the entrypoint is host-shell agnostic.
    $shellPath = Join-Path $PSHOME 'powershell.exe'
}
if (-not (Test-Path -LiteralPath $shellPath)) {
    throw "No PowerShell host found for the lifecycle test: $shellPath"
}
$scenarios = @('success', 'keep', 'failed', 'cleanup-failed', 'nonempty', 'external', 'parent-link', 'child-link', 'owner-changed', 'invalid-id', 'offline-success', 'offline-failed', 'offline-keep')
try {
    # Exercise source preflight against real Git state, without Docker or bundles.
    $sourceRoot = Join-Path $testRoot 'offline-source'
    New-Item -ItemType Directory -Path (Join-Path $sourceRoot 'scripts') -Force | Out-Null
    foreach ($file in @('verify_offline_install.ps1', 'quality_output.ps1')) {
        Copy-Item -LiteralPath (Join-Path $repoRoot "scripts/$file") -Destination (Join-Path $sourceRoot 'scripts')
    }
    Set-Content -LiteralPath (Join-Path $sourceRoot 'scripts/release_contract.py') -Value '# committed manifest generator'
    Set-Content -LiteralPath (Join-Path $sourceRoot 'README.md') -Value 'documentation'
    # Keep the fixture repository byte-stable on Windows hosts whose global
    # autocrlf setting would otherwise emit line-ending warnings during git.
    $env:GIT_CONFIG_COUNT = '1'
    $env:GIT_CONFIG_KEY_0 = 'core.autocrlf'
    $env:GIT_CONFIG_VALUE_0 = 'false'
    git -C $sourceRoot init --quiet 2>$null
    git -C $sourceRoot add . 2>$null
    git -C $sourceRoot -c user.name=Fixture -c user.email=fixture@example.invalid -c core.hooksPath=/dev/null commit --quiet -m fixture 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'Cannot initialize source preflight fixture.' }
    function docker { throw 'source-preflight-passed' }
    Add-Content -LiteralPath (Join-Path $sourceRoot 'README.md') -Value 'uncommitted documentation'
    foreach ($dirtyManifest in @($false, $true)) {
        if ($dirtyManifest) {
            Add-Content -LiteralPath (Join-Path $sourceRoot 'scripts/release_contract.py') -Value '# changed behavior'
        }
        $failure = $null
        try { & (Join-Path $sourceRoot 'scripts/verify_offline_install.ps1') }
        catch { $failure = $_.Exception.Message }
        $expected = if ($dirtyManifest) { 'Commit runtime/build inputs' } else { 'source-preflight-passed' }
        if (-not $failure -or -not $failure.StartsWith($expected)) { throw "Unexpected source preflight: $failure" }
        if (Test-Path -LiteralPath (Join-Path $sourceRoot 'tmp')) { throw 'Preflight created output before validation.' }
    }
    Write-Output 'PASS offline-source-preflight'

    # Run the installer's real existing-env branch, stopping before service writes.
    $installRoot = Join-Path $testRoot 'installer-update'
    New-Item -ItemType Directory -Path $installRoot | Out-Null
    Copy-Item -LiteralPath (Join-Path $repoRoot 'install.ps1') -Destination $installRoot
    $sourceId = 'a' * 40
    Set-Content -LiteralPath (Join-Path $installRoot 'release.env') -Value @(
        'DRAMAFORGE_VERSION=fixture', "DRAMAFORGE_SOURCE_COMMIT=$sourceId",
        'DRAMAFORGE_BACKEND_IMAGE=backend:fixture', 'DRAMAFORGE_FRONTEND_IMAGE=frontend:fixture')
    $envPath = Join-Path $installRoot '.env'
    Set-Content -LiteralPath $envPath -Value @('SESSION_SECRET=synthetic-secret', 'DRAMAFORGE_VERSION=old')
    function docker {
        if (($args -join ' ') -eq 'compose version') { $global:LASTEXITCODE = 0; return }
        throw 'installer-before-services'
    }
    Push-Location
    try {
        $failure = $null
        try { & (Join-Path $installRoot 'install.ps1') }
        catch { $failure = $_.Exception.Message }
        if ($failure -ne 'installer-before-services') { throw "Unexpected installer result: $failure" }
    } finally { Pop-Location }
    $updated = Get-Content -LiteralPath $envPath
    foreach ($line in @('SESSION_SECRET=synthetic-secret', 'DRAMAFORGE_VERSION=fixture', "DRAMAFORGE_SOURCE_COMMIT=$sourceId")) {
        if ($line -notin $updated) { throw 'Installer lost settings or release identity.' }
    }
    if (@(Get-ChildItem -LiteralPath $installRoot -Filter '.env.updating.*' -Force).Count) { throw 'Installer retained temporary secrets.' }
    Write-Output 'PASS installer-update'

    # Run the actual save/compress block with a small synthetic Docker stream.
    $tokens = $null
    $parseErrors = $null
    $tree = [Management.Automation.Language.Parser]::ParseFile(
        (Join-Path $repoRoot 'scripts/verify_offline_install.ps1'), [ref]$tokens, [ref]$parseErrors)
    if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
    $archiveBlock = $tree.Find({ param($node)
        $node -is [Management.Automation.Language.TryStatementAst] -and
        $node.Body.Statements[0].Extent.Text.StartsWith('docker save ')
    }, $true)
    if (-not $archiveBlock) { throw 'Missing archive lifecycle block.' }
    foreach ($saveFails in @($false, $true)) {
        $work = Join-Path $testRoot "archive-$saveFails"
        $bundle = Join-Path $work 'bundle'
        New-Item -ItemType Directory -Path $bundle -Force | Out-Null
        $tarPath = Join-Path $work 'images.tar'
        $runtimeImages = @('synthetic:image')
        function docker {
            [IO.File]::WriteAllBytes($args[2], [byte[]](1, 2, 3, 4))
            $global:LASTEXITCODE = if ($saveFails) { 1 } else { 0 }
        }
        $failed = $false
        try { . ([scriptblock]::Create($archiveBlock.Extent.Text)) }
        catch { if (-not $saveFails) { throw }; $failed = $true }
        if ($failed -ne $saveFails -or (Test-Path -LiteralPath $tarPath)) {
            throw 'Archive failure propagation or raw intermediate cleanup failed.'
        }
        if (-not $saveFails) {
            $stream = [IO.File]::OpenRead((Join-Path $bundle 'images.tar.gz'))
            $gzip = [IO.Compression.GZipStream]::new($stream, [IO.Compression.CompressionMode]::Decompress)
            try {
                foreach ($expected in 1, 2, 3, 4, -1) {
                    if ($gzip.ReadByte() -ne $expected) { throw 'Compressed stream content changed.' }
                }
            } finally { $gzip.Dispose(); $stream.Dispose() }
        }
    }
    Write-Output 'PASS offline-archive-lifecycle'

    foreach ($name in $scenarios) {
        $caseRoot = Join-Path $testRoot $name
        New-Item -ItemType Directory -Path (Join-Path $caseRoot 'scripts') -Force | Out-Null
        Copy-Item -LiteralPath (Join-Path $repoRoot 'scripts/run_quality_in_docker.ps1') -Destination (Join-Path $caseRoot 'scripts')
        Copy-Item -LiteralPath (Join-Path $repoRoot 'scripts/quality_output.ps1') -Destination (Join-Path $caseRoot 'scripts')
        Copy-Item -LiteralPath (Join-Path $repoRoot 'scripts/verify_offline_install.ps1') -Destination (Join-Path $caseRoot 'scripts')
        $previousPreference = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            $result = & $shellPath -NoProfile -File $PSCommandPath -Scenario $name -ScenarioRoot $caseRoot 2>&1
            $resultCode = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $previousPreference
        }
        $expectedCode = if ($name -eq 'failed') { 17 }
            elseif ($name -in @('cleanup-failed', 'nonempty', 'child-link', 'owner-changed', 'invalid-id')) { 1 }
            else { 0 }
        if ($resultCode -ne $expectedCode) {
            throw "${name}: expected exit $expectedCode, got $resultCode. $result"
        }
        $output = if ($name -eq 'external') { Join-Path $caseRoot 'outside/output' }
            else { Join-Path $caseRoot 'tmp/output' }
        if ((Test-Path -LiteralPath $output) -ne ($name -notin @('success', 'offline-success'))) {
            throw "${name}: unexpected output retention. $result"
        }
        if ((Get-Content -LiteralPath (Join-Path $caseRoot 'outside/sentinel') -Raw).Trim() -ne 'keep') {
            throw "${name}: unrelated data changed."
        }
        if ($name -eq 'nonempty') {
            if ((Get-Content -LiteralPath (Join-Path $output 'sentinel') -Raw).Trim() -ne 'keep') {
                throw 'Existing output was changed.'
            }
            if (Select-String -LiteralPath (Join-Path $caseRoot 'calls.txt') -Pattern ' build | down ') {
                throw 'Rejected preflight must not build or tear down resources.'
            }
        }
        $callsFile = Join-Path $caseRoot 'calls.txt'
        $calls = if (Test-Path -LiteralPath $callsFile) { Get-Content -LiteralPath $callsFile -Raw } else { '' }
        if ($name.StartsWith('offline-')) {
            if ($calls -notmatch '-p dramaforge-install-synthetic down --volumes --remove-orphans') {
                throw "${name}: owned install resources were not reclaimed."
            }
        } elseif ($expectedCode -eq 0) {
            $position = -1
            foreach ($stage in @('run .* backend-quality', 'run .* frontend-quality',
                '--exit-code-from media-resource-quality', '--exit-code-from auth-gateway-integration-quality',
                '--exit-code-from litellm-integration-quality')) {
                $match = [regex]::Match($calls, $stage)
                if (-not $match.Success -or $match.Index -le $position) { throw "${name}: missing or reordered stage $stage" }
                $position = $match.Index
            }
        }
        if ($calls -match '(?m)^image ' -or $calls -match '--rmi') {
            throw "${name}: shared quality images must be retained."
        }
        Write-Output "PASS $name"
    }
} finally {
    # Remove only this harness's temporary fixtures, unlinking before recursion.
    $resolvedRoot = [IO.Path]::GetFullPath($testRoot)
    $expectedParent = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\', '/')
    if ((Split-Path -Parent $resolvedRoot).TrimEnd('\', '/') -ne $expectedParent -or
        (Split-Path -Leaf $resolvedRoot) -notmatch '^df-quality-lifecycle-[0-9a-f]{32}$') {
        throw 'Unsafe test cleanup path.'
    }
    if (Test-Path -LiteralPath $resolvedRoot) {
        $pending = [Collections.Generic.Stack[string]]::new()
        $pending.Push($resolvedRoot)
        while ($pending.Count -gt 0) {
            foreach ($entry in Get-ChildItem -LiteralPath $pending.Pop() -Force) {
                if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                    [IO.Directory]::Delete($entry.FullName)
                } elseif ($entry.PSIsContainer) { $pending.Push($entry.FullName) }
            }
        }
        Remove-Item -LiteralPath $resolvedRoot -Recurse -Force
    }
}

# Expected child failures must not become the test harness's exit status.
$global:LASTEXITCODE = 0
Write-Output 'All lifecycle scenarios passed.'
