#!/usr/bin/env pwsh
# Test Kraken Trader connections

Write-Host ""
Write-Host "=== Testing Kraken Trader Connections ===" -ForegroundColor Green

# Test REST API
Write-Host ""
Write-Host "1. Testing REST API..." -ForegroundColor Yellow
try {
    $response = [System.Net.WebClient]::new().DownloadString("http://localhost:8080/api/status")
    $json = $response | ConvertFrom-Json
    Write-Host "   OK - API Status: $($json.status)" -ForegroundColor Green
    Write-Host "   OK - Stage: $($json.stage)" -ForegroundColor Green
    Write-Host "   OK - Simulation Mode: $($json.simulation_mode)" -ForegroundColor Green
} catch {
    Write-Host "   ERROR - API Error: $_" -ForegroundColor Red
}

# Test Portfolio endpoint
Write-Host ""
Write-Host "2. Testing Portfolio endpoint..." -ForegroundColor Yellow
try {
    $response = [System.Net.WebClient]::new().DownloadString("http://localhost:8080/portfolio")
    $json = $response | ConvertFrom-Json
    Write-Host "   OK - Total Value: $($json.total_value) $($json.quote_currency)" -ForegroundColor Green
    Write-Host "   OK - Available: $($json.available_quote)" -ForegroundColor Green
} catch {
    Write-Host "   ERROR - Portfolio Error: $_" -ForegroundColor Red
}

# Test WebSocket endpoint
Write-Host ""
Write-Host "3. WebSocket endpoint available at:" -ForegroundColor Yellow
Write-Host "   ws://localhost:8080/ws/portfolio" -ForegroundColor Cyan
Write-Host "   (WebSocket connections must be tested from browser)" -ForegroundColor Gray

Write-Host ""
Write-Host "4. Dashboard available at:" -ForegroundColor Yellow
Write-Host "   http://localhost:8080/dashboard/index.html" -ForegroundColor Cyan

Write-Host ""
Write-Host "=== Test Complete ===" -ForegroundColor Green