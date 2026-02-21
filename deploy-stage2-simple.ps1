#!/usr/bin/env pwsh
Write-Host "Deploying Stage 2 to Cloud Run..." -ForegroundColor Green

# Simple deployment with stage 2
gcloud run deploy kraken-trader --project cryptotrading-485110 --region australia-southeast1 --source . --set-env-vars STAGE=stage2,SIMULATION_MODE=true