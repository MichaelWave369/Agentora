# Phi Desktop Bridge R10: Windows Field Lab (offline preflight / guidance only)
# No software installations, desktop operations, policy changes, uploads, or file writes.
[CmdletBinding()]
param([switch]$Json, [switch]$Plan)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repo = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$required = @(
    "server\app\services\desktop_windows_restricted_ipc.py",
    "server\app\services\desktop_windows_field_validation.py",
    "server\app\services\desktop_field_ledger.py",
    "server\app\services\desktop_operator_desk.py"
)
$sourcePresent = $true
foreach ($path in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $repo $path) -PathType Leaf)) {
        $sourcePresent = $false
    }
}
$windows = [System.Environment]::OSVersion.Platform -eq [System.PlatformID]::Win32NT
$pythonVisible = $null -ne (Get-Command -Name "python" -CommandType Application -ErrorAction SilentlyContinue)
$desktopCliVisible = $null -ne (Get-Command -Name "agent-desktop" -CommandType Application -ErrorAction SilentlyContinue)

$report = [ordered]@{
    schema = 1
    kit = "phi_desktop_bridge_r10"
    mode = "offline_preflight_only"
    windows_platform = [bool]$windows
    python_command_visible = [bool]$pythonVisible
    agent_desktop_command_visible = [bool]$desktopCliVisible
    local_agentora_source_present = [bool]$sourcePresent
    python_runtime_tested = $false
    pywin32_import_tested = $false
    actual_desktop_test_performed = $false
    cross_account_denial_verified = $false
    independent_security_review_complete = $false
    autonomous_execution_authorized = $false
    desktop_mutation_performed = $false
    system_configuration_modified = $false
    cloud_contact_performed = $false
    report_written_to_disk = $false
}

if ($Json) {
    # Does not include paths, usernames, keys, screenshot data or UI labels.
    $report | ConvertTo-Json -Depth 3 -Compress
    return
}

Write-Output "PHI DESKTOP FIELD LAB | R10 | OFFLINE PREFLIGHT"
Write-Output "This is guidance, not a security certificate."
Write-Output ("Windows host: " + $windows)
Write-Output ("Agentora source present: " + $sourcePresent)
Write-Output ("Python command visible (NOT tested): " + $pythonVisible)
Write-Output ("Desktop CLI command visible (NOT tested): " + $desktopCliVisible)
Write-Output ""
Write-Output "UNVERIFIED: actual desktop, cross-user access denial, security review."
Write-Output "AUTONOMOUS DESKTOP ACTIONS: NOT AUTHORIZED"
Write-Output "This script has not changed any computer settings."
Write-Output ""
Write-Output "OPTIONAL SUPERVISED FIELD PLAN. Never share session keys:"
Write-Output "1. Review docs/DESKTOP_BRIDGE_R6_WINDOWS_SID_PIPE.md."
Write-Output "2. Manually prepare Python, pywin32, and upstream CLI if desired."
Write-Output "3. Manually open a harmless app such as Calculator."
Write-Output "4. In terminal A, from the Agentora checkout:"
Write-Output '   $env:PYTHONPATH = "server"'
Write-Output '   python -m app.services.desktop_windows_restricted_ipc doctor'
Write-Output '   python -m app.services.desktop_windows_restricted_ipc start --app Calculator'
Write-Output "5. In terminal B, from the same checkout:"
Write-Output '   $env:PYTHONPATH = "server"'
Write-Output '   python -m app.services.desktop_windows_field_validation doctor'
Write-Output '   python -m app.services.desktop_windows_field_validation probe --address "<pipe-from-A>" --two-observations --receipt-file "calculator-test.json"'
Write-Output "6. After reviewing the receipt, optionally record YOUR observation:"
Write-Output '   python -m app.services.desktop_field_ledger record --receipt "calculator-test.json" --status observed'
Write-Output '   python -m app.services.desktop_field_ledger readiness'
Write-Output "7. Optionally use the read-only Operator Desk readiness panel:"
Write-Output '   python -m app.services.desktop_operator_desk --policy "examples/desktop-bridge/operator-policy.example.json"'
Write-Output "8. Stop terminal A with Ctrl+C after the trial."
Write-Output ""
Write-Output "DO NOT turn a successful observation into execution permission."
