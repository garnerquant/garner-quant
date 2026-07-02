$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$statusPath = Join-Path $projectRoot "data\live_runtime_status.json"
$runtimePattern = "runtime[\\/]+live_runtime\.py"

function Get-GarnerQuantRuntimeProcess {
    Get-CimInstance Win32_Process -Filter "name = 'python.exe'" |
        Where-Object {
            $_.CommandLine -and $_.CommandLine -match $runtimePattern
        }
}

function Format-Age {
    param([Nullable[double]]$Seconds)

    if ($null -eq $Seconds) {
        return "unknown"
    }

    $secondsValue = [Math]::Max(0, [int]$Seconds)
    $span = [TimeSpan]::FromSeconds($secondsValue)

    if ($span.TotalDays -ge 1) {
        return "{0}d {1}h" -f [int]$span.TotalDays, $span.Hours
    }
    if ($span.TotalHours -ge 1) {
        return "{0}h {1}m" -f [int]$span.TotalHours, $span.Minutes
    }
    if ($span.TotalMinutes -ge 1) {
        return "{0}m {1}s" -f [int]$span.TotalMinutes, $span.Seconds
    }
    return "{0}s" -f $span.Seconds
}

function ConvertTo-DateTimeOffset {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $null
    }

    $normalized = $Value.Replace("Z", "+00:00")
    try {
        return [DateTimeOffset]::Parse($normalized)
    } catch {
        return $null
    }
}

function Get-FreshnessLabel {
    param([Nullable[double]]$AgeSeconds)

    if ($null -eq $AgeSeconds) {
        return "Missing"
    }
    if ($AgeSeconds -le 60) {
        return "Live"
    }
    if ($AgeSeconds -le 300) {
        return "Recent"
    }
    if ($AgeSeconds -le 900) {
        return "Slightly stale"
    }
    if ($AgeSeconds -le 3600) {
        return "Stale"
    }
    return "Very stale"
}

function Get-HeartbeatLabel {
    param(
        [Nullable[double]]$AgeSeconds,
        [int]$CycleSeconds
    )

    if ($null -eq $AgeSeconds) {
        return "Missing"
    }

    $delayedAfter = [Math]::Max($CycleSeconds * 3, 900)
    $overdueAfter = [Math]::Max($CycleSeconds * 6, 1800)

    if ($AgeSeconds -ge $overdueAfter) {
        return "Overdue"
    }
    if ($AgeSeconds -ge $delayedAfter) {
        return "Delayed"
    }
    return "Healthy"
}

$runtimeProcesses = @(Get-GarnerQuantRuntimeProcess)
if ($runtimeProcesses.Count -eq 0) {
    Write-Host "Runtime process: not running"
} else {
    Write-Host "Runtime process: running"
    foreach ($process in $runtimeProcesses) {
        Write-Host "PID: $($process.ProcessId)"
        Write-Host "Command: $($process.CommandLine)"
    }
}

if (-not (Test-Path -LiteralPath $statusPath)) {
    Write-Host "Runtime status file: missing ($statusPath)"
    exit 0
}

$statusFile = Get-Item -LiteralPath $statusPath
Write-Host "Runtime status file: $statusPath"
Write-Host "Status file modified: $($statusFile.LastWriteTime.ToString('o'))"

try {
    $status = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
} catch {
    Write-Host "Runtime status file could not be parsed: $($_.Exception.Message)"
    exit 1
}

$latestEventTimestamp = $null
if ($status.latest_runtime_event -and $status.latest_runtime_event.timestamp) {
    $latestEventTimestamp = [string]$status.latest_runtime_event.timestamp
}

$candidates = @(
    [string]$status.updated_at,
    [string]$status.last_cycle_at,
    $latestEventTimestamp,
    $statusFile.LastWriteTime.ToUniversalTime().ToString("o")
) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }

$latestTimestamp = $null
foreach ($candidate in $candidates) {
    $parsed = ConvertTo-DateTimeOffset -Value $candidate
    if ($null -ne $parsed -and ($null -eq $latestTimestamp -or $parsed -gt $latestTimestamp)) {
        $latestTimestamp = $parsed
    }
}

$now = [DateTimeOffset]::UtcNow
$freshnessAgeSeconds = $null
if ($null -ne $latestTimestamp) {
    $freshnessAgeSeconds = [Math]::Max(0, ($now - $latestTimestamp.ToUniversalTime()).TotalSeconds)
}

$heartbeatTimestamp = ConvertTo-DateTimeOffset -Value ([string]$status.last_cycle_at)
$heartbeatAgeSeconds = $null
if ($null -ne $heartbeatTimestamp) {
    $heartbeatAgeSeconds = [Math]::Max(0, ($now - $heartbeatTimestamp.ToUniversalTime()).TotalSeconds)
}

$cycleSeconds = 300
if ($status.cycle_seconds) {
    $cycleSeconds = [int]$status.cycle_seconds
}

Write-Host "Runtime status: $($status.status)"
Write-Host "Last cycle at: $($status.last_cycle_at)"
Write-Host "Latest runtime event: $latestEventTimestamp"
Write-Host "Freshness timestamp: $latestTimestamp"
Write-Host "Freshness: $(Get-FreshnessLabel -AgeSeconds $freshnessAgeSeconds) ($(Format-Age -Seconds $freshnessAgeSeconds) ago)"
Write-Host "Heartbeat: $(Get-HeartbeatLabel -AgeSeconds $heartbeatAgeSeconds -CycleSeconds $cycleSeconds) ($(Format-Age -Seconds $heartbeatAgeSeconds) ago)"
Write-Host "Cycle count: $($status.cycle_count)"
Write-Host "Current stage: $($status.current_strategy_stage)"
Write-Host "Last error: $(if ($status.last_error) { $status.last_error } else { 'None' })"
