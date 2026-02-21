@echo off
REM Start Kraken Trader Server

echo Starting Kraken Trader Server...
cd /d "%~dp0"

REM Set environment variables
set STAGE=stage2
set SIMULATION_MODE=true
set LOG_LEVEL=INFO
set HOST=0.0.0.0
set PORT=8080

echo.
echo Server will start on http://localhost:8080
echo Dashboard: http://localhost:8080/dashboard/index.html
echo.
echo Press Ctrl+C to stop the server
echo.

REM Start the server
python main.py

pause