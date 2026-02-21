#!/usr/bin/env pwsh
# Deploy as new service kraken-trader-v2

Write-Host "==========================================="  -ForegroundColor Green
Write-Host "Deploying NEW Service: kraken-trader-v2"  -ForegroundColor Green
Write-Host "==========================================="  -ForegroundColor Green

$PROJECT_ID = "cryptotrading-485110"
$REGION = "australia-southeast1"
$SERVICE_NAME = "kraken-trader-v2"

Write-Host ""
Write-Host "Building and deploying as new service..." -ForegroundColor Yellow

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
  --set-env-vars STAGE=stage2,SIMULATION_MODE=true,MULTI_TIMEFRAME_ENABLED=true,CHECK_INTERVAL_MINUTES=15

Write-Host ""
Write-Host "Deployment started..." -ForegroundColor Green