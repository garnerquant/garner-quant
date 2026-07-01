$ErrorActionPreference = "Stop"

Set-Location -Path (Join-Path $PSScriptRoot "..")
python -m streamlit run web_dashboard.py --server.address 0.0.0.0 --server.port 8501
