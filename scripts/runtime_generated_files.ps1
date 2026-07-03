$ErrorActionPreference = "Stop"

function Get-GarnerQuantProjectRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

function Get-GarnerQuantRuntimeGeneratedFiles {
    param(
        [string]$ProjectRoot = (Get-GarnerQuantProjectRoot)
    )

    $manifestPath = Join-Path $ProjectRoot "runtime\generated_runtime_files.txt"
    if (-not (Test-Path -LiteralPath $manifestPath)) {
        throw "Runtime generated file manifest not found: $manifestPath"
    }

    Get-Content -LiteralPath $manifestPath |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ -and -not $_.StartsWith("#") } |
        ForEach-Object { $_.Replace("\", "/") }
}

function Test-GarnerQuantGeneratedPath {
    param(
        [string]$Path,
        [string[]]$GeneratedPaths
    )

    $normalized = $Path.Replace("\", "/").Trim('"')
    foreach ($generatedPath in $GeneratedPaths) {
        $generated = $generatedPath.Replace("\", "/").TrimEnd("/")
        if ($generatedPath.EndsWith("/")) {
            if ($normalized -eq $generated -or $normalized.StartsWith("$generated/")) {
                return $true
            }
        } elseif ($normalized -eq $generated) {
            return $true
        }
    }

    return $false
}

function Get-GarnerQuantRuntimeProcess {
    $runtimePattern = "runtime[\\/]+live_runtime\.py"
    Get-CimInstance Win32_Process -Filter "name = 'python.exe'" |
        Where-Object {
            $_.CommandLine -and $_.CommandLine -match $runtimePattern
        }
}

function Get-GitStatusPath {
    param([string]$StatusLine)

    if ($StatusLine.Length -lt 4) {
        return ""
    }

    $path = $StatusLine.Substring(3).Trim()
    if ($path.Contains(" -> ")) {
        $path = ($path -split " -> ")[-1]
    }

    return $path.Trim('"').Replace("\", "/")
}

function Enable-GarnerQuantRuntimeFileProtection {
    param(
        [string]$ProjectRoot = (Get-GarnerQuantProjectRoot)
    )

    Push-Location $ProjectRoot
    try {
        $generatedPaths = Get-GarnerQuantRuntimeGeneratedFiles -ProjectRoot $ProjectRoot |
            Where-Object { -not $_.EndsWith("/") }

        foreach ($path in $generatedPaths) {
            git ls-files --error-unmatch -- $path *> $null
            if ($LASTEXITCODE -eq 0) {
                git update-index --skip-worktree -- $path
            }
        }
    } finally {
        Pop-Location
    }
}
