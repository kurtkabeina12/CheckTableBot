@echo off
cd /d "%~dp0"
echo Starting WebApp on http://localhost:8080 ...
python -m uvicorn server:app --host 0.0.0.0 --port 8080
