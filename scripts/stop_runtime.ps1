$ErrorActionPreference = "Stop"

$runtimePattern = "runtime[\\/]+live_runtime\.py"

function Get-GarnerQuantRuntimeProcess {
    Get-CimInstance Win32_Process -Filter "name = 'python.exe'" |
        Where-Object {
            $_.CommandLine -and $_.CommandLine -match $runtimePattern
        }
}

$runtimeProcesses = @(Get-GarnerQuantRuntimeProcess)
if ($runtimeProcesses.Count -eq 0) {
    Write-Host "Garner Quant runtime is not running."
    exit 0
}

foreach ($process in $runtimeProcesses) {
    Write-Host "Stopping Garner Quant runtime PID $($process.ProcessId)"
    Write-Host "Command: $($process.CommandLine)"
    Stop-Process -Id $process.ProcessId -Force
}

Start-Sleep -Seconds 1
$remaining = @(Get-GarnerQuantRuntimeProcess)
if ($remaining.Count -eq 0) {
    Write-Host "Garner Quant runtime stopped."
    exit 0
}

Write-Host "Some runtime processes are still running:"
foreach ($process in $remaining) {
    Write-Host "PID: $($process.ProcessId)"
    Write-Host "Command: $($process.CommandLine)"
}
exit 1
