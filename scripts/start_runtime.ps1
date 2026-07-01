$ErrorActionPreference = "Stop"

Set-Location -Path (Join-Path $PSScriptRoot "..")
python runtime/live_runtime.py
