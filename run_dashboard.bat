@echo off
cd /d %~dp0
set AI_BI_NL2SQL_ROOT=C:\Users\BharadNa\dataiku-langgraph-nlq
set PYTHONPATH=%CD%;%AI_BI_NL2SQL_ROOT%\src
py -3 -m streamlit run frontend/app/main.py --server.port 8501
