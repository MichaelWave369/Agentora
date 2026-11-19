#Requires -Version 5.1
# Owner-scoped, interactive-user Windows runner for the existing Agentora R9 -> R1 lane.
[CmdletBinding()]
param(
    [ValidateSet('Install', 'Run', 'Probe', 'Status', 'Remove')]
    [string] $Mode = 'Status',
    [string] $PythonExe = '',
    [string] $SnapshotPath = ''
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'R9_R1_WINDOWS_ONLY' }
$taskName = 'Phi369-Agentora-R9R1'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$stateDir = Join-Path $env:LOCALAPPDATA 'Phi369\AgentoraR9R1'
$configFile = Join-Path $stateDir 'runner.json'
$secretFile = Join-Path $stateDir 'credentials.clixml'

function Read-Config {
    if (-not (Test-Path -LiteralPath $configFile -PathType Leaf)) { throw 'R9_R1_RUNNER_NOT_INSTALLED' }
    $config = Get-Content -LiteralPath $configFile -Raw | ConvertFrom-Json
    if ($config.schema -ne 1) { throw 'R9_R1_CONFIG_SCHEMA_UNSUPPORTED' }
    return $config
}
function Test-TrustedCheckout([object] $config) {
    if ($repo -ne $config.repo) { throw 'R9_R1_CHECKOUT_PATH_CHANGED' }
    if (-not (Test-Path -LiteralPath $config.python -PathType Leaf)) { throw 'R9_R1_PYTHON_NOT_FOUND' }
    $head = (& git -C $repo rev-parse HEAD 2>$null)
    if ($LASTEXITCODE -ne 0 -or $head -ne $config.sha) { throw 'R9_R1_HEAD_CHANGED_REINSTALL_AFTER_REVIEW' }
    $dirty = @(& git -C $repo status --porcelain --untracked-files=no 2>$null)
    if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw 'R9_R1_CHECKOUT_NOT_CLEAN' }
}
function Convert-Secret([System.Security.SecureString] $value) {
    $pointer = [IntPtr]::Zero
    try {
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($value)
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    } finally {
        if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    }
}
switch ($Mode) {
    'Install' {
        if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
            throw 'R9_R1_TASK_EXISTS_REMOVE_BEFORE_REINSTALL'
        }
        if (-not $PythonExe) {
            $command = Get-Command python -CommandType Application -ErrorAction Stop | Select-Object -First 1
            $PythonExe = $command.Source
        }
        $PythonExe = [IO.Path]::GetFullPath($PythonExe)
        if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) { throw 'R9_R1_PYTHON_NOT_FOUND' }
        & $PythonExe -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'
        if ($LASTEXITCODE -ne 0) { throw 'R9_R1_PYTHON_311_REQUIRED' }

        $head = (& git -C $repo rev-parse HEAD 2>$null)
        if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') { throw 'R9_R1_GIT_HEAD_UNAVAILABLE' }
        if (@(& git -C $repo status --porcelain --untracked-files=no).Count -gt 0) { throw 'R9_R1_CHECKOUT_NOT_CLEAN' }
        New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
        if (-not $SnapshotPath) { $SnapshotPath = Join-Path $stateDir 'r9-turns.json' }
        $SnapshotPath = [IO.Path]::GetFullPath($SnapshotPath)
        New-Item -ItemType Directory -Path (Split-Path -Parent $SnapshotPath) -Force | Out-Null

        Write-Host 'Enter an expiring Agentora-only Actions read/write token (hidden):'
        $dispatch = Read-Host -AsSecureString
        Write-Host 'Enter an Agentora-only Actions/Contents/PR/Checks read token (hidden):'
        $reader = Read-Host -AsSecureString
        if ($dispatch.Length -eq 0 -or $reader.Length -eq 0) { throw 'R9_R1_BOTH_TOKENS_REQUIRED' }
        # Export-Clixml protects SecureStrings with per-user Windows DPAPI.
        [pscustomobject]@{ Dispatch = $dispatch; Read = $reader } | Export-Clixml -LiteralPath $secretFile
        [pscustomobject]@{ schema = 1; repo = $repo; sha = $head; python = $PythonExe; snapshot = $SnapshotPath } | ConvertTo-Json | Set-Content -LiteralPath $configFile -Encoding UTF8

        if ($PSCommandPath.Contains('"')) { throw 'R9_R1_SCRIPT_PATH_INVALID' }
        $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $taskArgs = '-NoLogo -NoProfile -NonInteractive -File "' + $PSCommandPath + '" -Mode Run'
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
        $action = New-ScheduledTaskAction -Execute $powershell -Argument $taskArgs -WorkingDirectory $repo
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
        $principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
        $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 2) -ExecutionTimeLimit ([TimeSpan]::Zero)
        Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Owner-scoped Agentora R9 to R1 watcher (interactive-user session)' | Out-Null
        Write-Host "INSTALLED $taskName at pinned Agentora HEAD $head"
        Write-Host 'Runs after sign-in; installing did not dispatch any mission.'
        Write-Host "Probe: & '$PSCommandPath' -Mode Probe"
        Write-Host "Start: Start-ScheduledTask -TaskName '$taskName'"
    }
    { $_ -eq 'Run' -or $_ -eq 'Probe' } {
        $config = Read-Config
        Test-TrustedCheckout $config
        if (-not (Test-Path -LiteralPath $secretFile -PathType Leaf)) { throw 'R9_R1_CREDENTIALS_MISSING' }
        $secrets = Import-Clixml -LiteralPath $secretFile
        if (-not ($secrets.Dispatch -is [System.Security.SecureString]) -or -not ($secrets.Read -is [System.Security.SecureString])) { throw 'R9_R1_CREDENTIALS_INVALID' }
        $env:AGENTORA_R1_DISPATCH_TOKEN = Convert-Secret $secrets.Dispatch
        $env:AGENTORA_R1_READ_TOKEN = Convert-Secret $secrets.Read
        try {
            Push-Location $repo
            try {
                if ($Mode -eq 'Probe') {
                    & $config.python -u 'scripts/fleet_r10_r1.py' watch --cycles 1 --snapshot $config.snapshot
                } else {
                    & $config.python -u 'scripts/fleet_r10_r1.py' watch --dispatch --snapshot $config.snapshot
                }
                $code = $LASTEXITCODE
            } finally {
                Pop-Location
            }
            if ($code -ne 0) { throw "R9_R1_WATCH_EXIT_$code" }
        } finally {
            Remove-Item Env:\AGENTORA_R1_DISPATCH_TOKEN -ErrorAction SilentlyContinue
            Remove-Item Env:\AGENTORA_R1_READ_TOKEN -ErrorAction SilentlyContinue
        }
    }
    'Status' {
        $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        if ($null -eq $task) { Write-Host 'NOT_INSTALLED' } else { Write-Host "TASK $taskName state=$($task.State)" }
        Write-Host "Config present: $(Test-Path -LiteralPath $configFile)"
        Write-Host "Encrypted credentials present: $(Test-Path -LiteralPath $secretFile)"
        if (Test-Path -LiteralPath $configFile) {
            $config = Read-Config
            Write-Host "Pinned source: $($config.sha)"
            Write-Host "Snapshot: $($config.snapshot)"
        }
    }
    'Remove' {
        $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        if ($null -ne $task) {
            Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
            Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        }
        Remove-Item -LiteralPath $secretFile -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $configFile -ErrorAction SilentlyContinue
        Write-Host 'REMOVED scheduled task and local credentials'
    }
}
