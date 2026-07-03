$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$logsDir = Join-Path $projectRoot "logs"
$runtimeLog = Join-Path $logsDir "runtime.log"
$runtimeScript = Join-Path $projectRoot "runtime\live_runtime.py"
$runtimePattern = "runtime[\\/]+live_runtime\.py"

function Get-GarnerQuantRuntimeProcess {
    Get-CimInstance Win32_Process -Filter "name = 'python.exe'" |
        Where-Object {
            $_.CommandLine -and $_.CommandLine -match $runtimePattern
        }
}

New-Item -ItemType Directory -Force -Path $logsDir | Out-Null
if (-not (Test-Path -LiteralPath $runtimeLog)) {
    New-Item -ItemType File -Path $runtimeLog | Out-Null
}

$existingRuntime = @(Get-GarnerQuantRuntimeProcess)
if ($existingRuntime.Count -gt 0) {
    Write-Host "Garner Quant runtime is already running."
    foreach ($process in $existingRuntime) {
        Write-Host "PID: $($process.ProcessId)"
        Write-Host "Command: $($process.CommandLine)"
    }
    Write-Host "Log: $runtimeLog"
    exit 0
}

if (-not (Test-Path -LiteralPath $runtimeScript)) {
    throw "Runtime script not found: $runtimeScript"
}

Push-Location $projectRoot
try {
    python -m runtime.startup_validation --root $projectRoot
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
} finally {
    Pop-Location
}

$command = @"
Set-Location -LiteralPath '$($projectRoot.Replace("'", "''"))'
python runtime/live_runtime.py *>> '$($runtimeLog.Replace("'", "''"))'
"@

$process = Start-Process `
    -FilePath "powershell.exe" `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $command) `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -PassThru

Start-Sleep -Seconds 2
$runtime = @(Get-GarnerQuantRuntimeProcess)

Write-Host "Started Garner Quant runtime launcher."
Write-Host "Launcher PID: $($process.Id)"
if ($runtime.Count -gt 0) {
    foreach ($runtimeProcess in $runtime) {
        Write-Host "Runtime PID: $($runtimeProcess.ProcessId)"
        Write-Host "Command: $($runtimeProcess.CommandLine)"
    }
} else {
    Write-Host "Runtime process was not visible yet. Check the log for startup errors."
}
Write-Host "Log: $runtimeLog"
