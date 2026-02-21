#!/usr/bin/env pwsh
# Deploy Kraken Trader with Stage 2 - Final Version

Write-Host "==========================================="  -ForegroundColor Green
Write-Host "Deploying Kraken Trader Stage 2"  -ForegroundColor Green
Write-Host "==========================================="  -ForegroundColor Green

# Configuration
$PROJECT_ID = "cryptotrading-485110"
$REGION = "australia-southeast1"
$SERVICE_NAME = "kraken-trader"

# Step 1: Delete old service
Write-Host ""
Write-Host "Step 1: Deleting old service..." -ForegroundColor Yellow
gcloud run services delete $SERVICE_NAME --region $REGION --quiet

# Step 2: Deploy new service with correct settings
Write-Host ""
Write-Host "Step 2: Deploying new service with Stage 2..." -ForegroundColor Yellow

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
Write-Host "Deployment initiated. This will take several minutes..." -ForegroundColor Yellow