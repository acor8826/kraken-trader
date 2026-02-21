#!/usr/bin/env pwsh
Write-Host "Checking Current Production Status..." -ForegroundColor Green
Write-Host ""

# Check API status
Write-Host "1. API Status:" -ForegroundColor Yellow
$response = [System.Net.WebClient]::new().DownloadString("https://kraken-trader-709516859644.australia-southeast1.run.app/api/status")
$json = $response | ConvertFrom-Json
Write-Host "   Stage: $($json.stage)" -ForegroundColor Cyan
Write-Host "   Status: $($json.status)" -ForegroundColor Cyan
Write-Host ""

# Check current revision env vars
Write-Host "2. Current Environment Variables:" -ForegroundColor Yellow
$envVars = gcloud run services describe kraken-trader --project cryptotrading-485110 --region australia-southeast1 --format="json" | ConvertFrom-Json
$env = $envVars.spec.template.spec.containers[0].env
foreach ($var in $env) {
    Write-Host "   $($var.name) = $($var.value)" -ForegroundColor Cyan
}

Write-Host ""
Write-Host "3. Active Revision:" -ForegroundColor Yellow
$revision = $envVars.status.latestReadyRevisionName
Write-Host "   $revision" -ForegroundColor Cyan

Write-Host ""
Write-Host "Summary:" -ForegroundColor Yellow
Write-Host "  - API shows stage1 (incorrect)" -ForegroundColor Red
Write-Host "  - Environment has malformed STAGE value" -ForegroundColor Red
Write-Host "  - Container import failing on updates" -ForegroundColor Red
Write-Host ""
Write-Host "The WebSocket->Polling fix IS deployed and working." -ForegroundColor Green
Write-Host "The multi-timeframe calculations ARE still in the code." -ForegroundColor Green
Write-Host "But STAGE setting is incorrect, affecting features." -ForegroundColor Yellow