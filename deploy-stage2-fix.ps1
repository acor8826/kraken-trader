#!/usr/bin/env pwsh
# Deploy Kraken Trader with Stage 2 configuration

Write-Host "==================================="  -ForegroundColor Green
Write-Host "Deploying with Stage 2 Configuration"  -ForegroundColor Green
Write-Host "==================================="  -ForegroundColor Green

# Configuration
$PROJECT_ID = "cryptotrading-485110"
$REGION = "australia-southeast1"
$SERVICE_NAME = "kraken-trader"

Write-Host ""
Write-Host "Building and deploying with Stage 2..." -ForegroundColor Yellow

# Deploy from source with environment variables
$envVars = @(
    "STAGE=stage2",
    "SIMULATION_MODE=true", 
    "MULTI_TIMEFRAME_ENABLED=true",
    "CHECK_INTERVAL_MINUTES=15",
    "MIN_HOLD_TIME_HOURS=0.5",
    "USE_FALLBACK_VOLATILITY=true",
    "PRIMARY_TIMEFRAMES=15m,1h,4h"
) -join ","

gcloud run deploy $SERVICE_NAME `
  --project $PROJECT_ID `
  --region $REGION `
  --source . `
  --platform managed `
  --memory 512Mi `
  --cpu 1 `
  --timeout 300 `
  --max-instances 5 `
  --allow-unauthenticated `
  --set-env-vars $envVars

if ($LASTEXITCODE -ne 0) {
    Write-Host "Deployment failed!" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "==================================="  -ForegroundColor Green
Write-Host "Stage 2 Deployment Complete!"  -ForegroundColor Green
Write-Host "==================================="  -ForegroundColor Green
Write-Host ""
Write-Host "Dashboard should now show:" -ForegroundColor Yellow
Write-Host "  - Stage: stage2 (NOT stage1)" -ForegroundColor Cyan
Write-Host "  - No cost stats errors" -ForegroundColor Cyan
Write-Host "  - Multi-timeframe analysis enabled" -ForegroundColor Cyan
Write-Host "  - WebSocket disabled with polling" -ForegroundColor Cyan