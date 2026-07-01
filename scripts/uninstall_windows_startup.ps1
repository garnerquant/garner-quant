[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

Import-Module ScheduledTasks

$taskNames = @(
    "GarnerQuantRuntime",
    "GarnerQuantDashboard"
)

foreach ($taskName in $taskNames) {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        Write-Host "Task not found: $taskName"
        continue
    }

    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Removed task: $taskName"
}

Write-Host "Garner Quant startup tasks uninstalled."
