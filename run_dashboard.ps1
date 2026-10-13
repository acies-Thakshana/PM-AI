# Local Streamlit dashboard + chatbot (no GitHub / no cloud)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$env:AI_BI_NL2SQL_ROOT = if ($env:AI_BI_NL2SQL_ROOT) { $env:AI_BI_NL2SQL_ROOT } else { "C:\Users\BharadNa\dataiku-langgraph-nlq" }
$env:PYTHONPATH = "$PSScriptRoot;$env:AI_BI_NL2SQL_ROOT\src"
$env:NLQ_SEMANTIC_ENABLED = "true"
$env:NLQ_SEMANTIC_CORE = "$PSScriptRoot\semantic\domains\kpi_productivity.yaml"
$env:NLQ_DATA_PATHS = "$PSScriptRoot\local_data\fixtures\KPI_data.parquet"
$env:NLQ_DATA_DATASETS = "KPI_data"
$env:NLQ_ALLOW_LOCAL_FALLBACK = "true"
Write-Host "Project: $PSScriptRoot"
Write-Host "NL2SQL:  $env:AI_BI_NL2SQL_ROOT"
Write-Host "KPI:     $env:NLQ_DATA_PATHS"
Write-Host "Open http://localhost:8501 after Streamlit starts"
py -3 -m streamlit run frontend/app/main.py --server.port 8501
