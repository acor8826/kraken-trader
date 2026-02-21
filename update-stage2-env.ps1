#!/usr/bin/env pwsh
Write-Host "Updating environment variables to Stage 2..." -ForegroundColor Green

# Update existing service with Stage 2 environment variables
gcloud run services update kraken-trader `
  --project cryptotrading-485110 `
  --region australia-southeast1 `
  --set-env-vars STAGE=stage2,SIMULATION_MODE=true,MULTI_TIMEFRAME_ENABLED=true,CHECK_INTERVAL_MINUTES=15 `
  --memory 512Mi `
  --cpu 1

Write-Host "Environment variables updated!" -ForegroundColor Green