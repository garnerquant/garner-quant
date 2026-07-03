$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "runtime_generated_files.ps1")

$projectRoot = Get-GarnerQuantProjectRoot
$generatedPaths = @(Get-GarnerQuantRuntimeGeneratedFiles -ProjectRoot $projectRoot)

Push-Location $projectRoot
try {
    $runtimeProcesses = @(Get-GarnerQuantRuntimeProcess)
    if ($runtimeProcesses.Count -gt 0) {
        Write-Host "Refusing to update while Garner Quant runtime is running."
        foreach ($process in $runtimeProcesses) {
            Write-Host "  PID $($process.ProcessId): $($process.CommandLine)"
        }
        Write-Host "Stop it first with scripts\stop_runtime.ps1."
        exit 1
    }

    python -m runtime.startup_validation --root $projectRoot
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    Enable-GarnerQuantRuntimeFileProtection -ProjectRoot $projectRoot

    $conflicts = @(git diff --name-only --diff-filter=U)
    if ($conflicts.Count -gt 0) {
        Write-Host "Refusing to update because merge conflicts already exist:"
        foreach ($path in $conflicts) {
            Write-Host "  $path"
        }
        exit 1
    }

    $sourcePaths = @()
    foreach ($line in @(git status --porcelain=v1 --untracked-files=all)) {
        $path = Get-GitStatusPath -StatusLine $line
        if (-not $path) {
            continue
        }
        if (-not (Test-GarnerQuantGeneratedPath -Path $path -GeneratedPaths $generatedPaths)) {
            $sourcePaths += $path
        }
    }
    $sourcePaths = @($sourcePaths | Sort-Object -Unique)

    $stashCreated = $false
    if ($sourcePaths.Count -gt 0) {
        $stashName = "garner-quant-source-before-update-{0}" -f (
            Get-Date -Format "yyyyMMdd-HHmmss"
        )
        Write-Host "Stashing source changes only:"
        foreach ($path in $sourcePaths) {
            Write-Host "  $path"
        }
        git stash push -u -m $stashName -- $sourcePaths
        $stashCreated = $true
    } else {
        Write-Host "No source changes to stash."
    }

    Write-Host "Pulling latest source with rebase..."
    git pull --rebase

    if ($stashCreated) {
        Write-Host "Restoring source changes..."
        git stash pop
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Stash pop reported conflicts. Generated runtime files were excluded."
            exit $LASTEXITCODE
        }
    }

    Enable-GarnerQuantRuntimeFileProtection -ProjectRoot $projectRoot

    python -m runtime.startup_validation --root $projectRoot
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    Write-Host "Repository update complete. Runtime generated files remain local."
} finally {
    Pop-Location
}
