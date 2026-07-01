[CmdletBinding()]
param(
    [switch]$StartNow
)

$ErrorActionPreference = "Stop"

function ConvertTo-PowerShellLiteral {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    return "'" + $Value.Replace("'", "''") + "'"
}

function New-GarnerQuantAction {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot,

        [Parameter(Mandatory = $true)]
        [string]$Command
    )

    $encodedCommand = [Convert]::ToBase64String(
        [System.Text.Encoding]::Unicode.GetBytes($Command)
    )

    return New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -EncodedCommand $encodedCommand" `
        -WorkingDirectory $ProjectRoot
}

Import-Module ScheduledTasks

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$logsDir = Join-Path $projectRoot "logs"
$runtimeLog = Join-Path $logsDir "runtime.log"
$dashboardLog = Join-Path $logsDir "dashboard.log"

New-Item -ItemType Directory -Force -Path $logsDir | Out-Null
foreach ($logPath in @($runtimeLog, $dashboardLog)) {
    if (-not (Test-Path -LiteralPath $logPath)) {
        New-Item -ItemType File -Path $logPath | Out-Null
    }
}

$projectRootLiteral = ConvertTo-PowerShellLiteral -Value $projectRoot
$runtimeLogLiteral = ConvertTo-PowerShellLiteral -Value $runtimeLog
$dashboardLogLiteral = ConvertTo-PowerShellLiteral -Value $dashboardLog

$runtimeCommand = @"
Set-Location -LiteralPath $projectRootLiteral
python runtime/live_runtime.py *>> $runtimeLogLiteral
"@

$dashboardCommand = @"
Set-Location -LiteralPath $projectRootLiteral
python -m streamlit run web_dashboard.py --server.address 0.0.0.0 --server.port 8501 *>> $dashboardLogLiteral
"@

$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

$runtimeTask = New-ScheduledTask `
    -Action (New-GarnerQuantAction -ProjectRoot $projectRoot -Command $runtimeCommand) `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "Start Garner Quant live runtime on user logon."

$dashboardTask = New-ScheduledTask `
    -Action (New-GarnerQuantAction -ProjectRoot $projectRoot -Command $dashboardCommand) `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "Start Garner Quant Streamlit dashboard on user logon."

Register-ScheduledTask -TaskName "GarnerQuantRuntime" -InputObject $runtimeTask -Force | Out-Null
Register-ScheduledTask -TaskName "GarnerQuantDashboard" -InputObject $dashboardTask -Force | Out-Null

if ($StartNow) {
    Start-ScheduledTask -TaskName "GarnerQuantRuntime"
    Start-ScheduledTask -TaskName "GarnerQuantDashboard"
}

Write-Host "Installed Garner Quant startup tasks."
Write-Host "Project root: $projectRoot"
Write-Host "Runtime log: $runtimeLog"
Write-Host "Dashboard log: $dashboardLog"
Write-Host "Tasks: GarnerQuantRuntime, GarnerQuantDashboard"
