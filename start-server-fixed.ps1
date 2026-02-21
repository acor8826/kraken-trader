#!/usr/bin/env pwsh
# Start Kraken Trader Server with fixed encoding

Write-Host "Starting Kraken Trader Server (Fixed Encoding)..." -ForegroundColor Green

# Change to script directory
Set-Location $PSScriptRoot

# Fix console encoding for Unicode characters
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

# Set environment variables for local development
$env:STAGE = "stage2"
$env:SIMULATION_MODE = "true"
$env:LOG_LEVEL = "INFO"
$env:HOST = "0.0.0.0"
$env:PORT = "8080"

# Check if server is already running
$port = 8080
$connection = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($connection) {
    Write-Host "Server is already running on port $port (PID: $($connection.OwningProcess))" -ForegroundColor Yellow
    Write-Host "Dashboard: http://localhost:$port/dashboard/index.html" -ForegroundColor Cyan
    return
}

Write-Host "Server will start on http://localhost:8080" -ForegroundColor Green
Write-Host "Dashboard: http://localhost:8080/dashboard/index.html" -ForegroundColor Cyan
Write-Host ""
Write-Host "Press Ctrl+C to stop the server" -ForegroundColor Yellow
Write-Host ""

# Start the server with UTF-8 encoding
python -X utf8 main.py