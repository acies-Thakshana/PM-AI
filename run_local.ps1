# Runs the AI4BI backend and the dashboard on this machine. No AWS account or model is needed.
# Usage:  .\run_local.ps1        then open http://127.0.0.1:8000/app/
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "backend")

if (-not (Test-Path ".venv")) {
    py -3 -m venv .venv
}
& .\.venv\Scripts\python.exe -m pip install -q -r requirements.txt
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
