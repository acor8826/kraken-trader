#!/usr/bin/env pwsh
# Start Kraken Trader Server

Write-Host "Starting Kraken Trader Server..." -ForegroundColor Green

# Change to script directory
Set-Location $PSScriptRoot

# Check if virtual environment exists
if (Test-Path "venv") {
    Write-Host "Activating virtual environment..." -ForegroundColor Yellow
    & .\venv\Scripts\Activate.ps1
} else {
    Write-Host "No virtual environment found. Creating one..." -ForegroundColor Yellow
    python -m venv venv
    & .\venv\Scripts\Activate.ps1
    Write-Host "Installing requirements..." -ForegroundColor Yellow
    pip install -r requirements.txt
}

# Set environment variables for local development
$env:STAGE = "stage2"
$env:SIMULATION_MODE = "true"
$env:LOG_LEVEL = "INFO"
$env:HOST = "0.0.0.0"
$env:PORT = "8080"

Write-Host "Starting server on http://localhost:8080" -ForegroundColor Green
Write-Host "Dashboard will be available at http://localhost:8080/dashboard/index.html" -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop the server" -ForegroundColor Yellow

# Start the server
python main.py