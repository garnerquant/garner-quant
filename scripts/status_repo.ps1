$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "runtime_generated_files.ps1")

$projectRoot = Get-GarnerQuantProjectRoot
$generatedPaths = @(Get-GarnerQuantRuntimeGeneratedFiles -ProjectRoot $projectRoot)

Push-Location $projectRoot
try {
    $runtimeProcesses = @(Get-GarnerQuantRuntimeProcess)
    if ($runtimeProcesses.Count -eq 0) {
        Write-Host "Runtime: not running"
    } else {
        Write-Host "Runtime: running"
        foreach ($process in $runtimeProcesses) {
            Write-Host "  PID $($process.ProcessId): $($process.CommandLine)"
        }
    }

    $statusLines = @(git status --porcelain=v1 --untracked-files=all)
    $conflicts = @(git diff --name-only --diff-filter=U)
    $generatedDirty = @()
    $sourceDirty = @()
    $untracked = @()

    foreach ($line in $statusLines) {
        $path = Get-GitStatusPath -StatusLine $line
        if (-not $path) {
            continue
        }

        if ($line.StartsWith("??")) {
            $untracked += $path
        }

        if (Test-GarnerQuantGeneratedPath -Path $path -GeneratedPaths $generatedPaths) {
            $generatedDirty += "$($line.Substring(0, 2)) $path"
        } else {
            $sourceDirty += "$($line.Substring(0, 2)) $path"
        }
    }

    Write-Host ""
    Write-Host "Merge conflicts: $($conflicts.Count)"
    foreach ($path in $conflicts) {
        Write-Host "  $path"
    }

    Write-Host ""
    Write-Host "Generated runtime files dirty: $($generatedDirty.Count)"
    foreach ($entry in $generatedDirty) {
        Write-Host "  $entry"
    }

    Write-Host ""
    Write-Host "Source files dirty: $($sourceDirty.Count)"
    foreach ($entry in $sourceDirty) {
        Write-Host "  $entry"
    }

    Write-Host ""
    Write-Host "Untracked files: $($untracked.Count)"
    foreach ($path in $untracked) {
        Write-Host "  $path"
    }

    Write-Host ""
    python -m runtime.startup_validation --root $projectRoot
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
} finally {
    Pop-Location
}
