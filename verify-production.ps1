#!/usr/bin/env pwsh
# Verify production deployment

Write-Host "Verifying Production Deployment..." -ForegroundColor Green
Write-Host ""

# Test API Status
Write-Host "1. Testing API Status endpoint..." -ForegroundColor Yellow
try {
    $response = [System.Net.WebClient]::new().DownloadString("https://kraken-trader-709516859644.australia-southeast1.run.app/api/status")
    $json = $response | ConvertFrom-Json
    Write-Host "   [OK] API Status: $($json.status)" -ForegroundColor Green
    Write-Host "   [OK] Stage: $($json.stage)" -ForegroundColor Green
    Write-Host "   [OK] Simulation Mode: $($json.simulation_mode)" -ForegroundColor Green
} catch {
    Write-Host "   [ERROR] API Error: $_" -ForegroundColor Red
}

# Test Cost Stats endpoint (previously broken)
Write-Host ""
Write-Host "2. Testing Cost Stats endpoint (previously broken)..." -ForegroundColor Yellow
try {
    $response = [System.Net.WebClient]::new().DownloadString("https://kraken-trader-709516859644.australia-southeast1.run.app/api/cost/stats")
    $json = $response | ConvertFrom-Json
    Write-Host "   [OK] Cost Stats Working!" -ForegroundColor Green
    Write-Host "   [OK] Enabled: $($json.enabled)" -ForegroundColor Green
    if ($json.error) {
        Write-Host "   ! Error field: $($json.error)" -ForegroundColor Yellow
    }
} catch {
    Write-Host "   [ERROR] Cost Stats Error: $_" -ForegroundColor Red
}

Write-Host ""
Write-Host "Dashboard URLs:" -ForegroundColor Yellow
Write-Host "   Production: https://kraken-trader-709516859644.australia-southeast1.run.app/dashboard/index.html" -ForegroundColor Cyan
Write-Host "   Alt URL: https://kraken-trader-rvltdsb3bq-ts.a.run.app/dashboard/index.html" -ForegroundColor Cyan
Write-Host ""
Write-Host "[OK] Deployment verification complete!" -ForegroundColor Green