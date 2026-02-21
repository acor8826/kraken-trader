#!/usr/bin/env pwsh
# Try deploying from a different registry approach

Write-Host "Trying deployment from artifact registry..." -ForegroundColor Green

# First, list available images
Write-Host ""
Write-Host "Available images in registry:" -ForegroundColor Yellow
gcloud artifacts docker images list australia-southeast1-docker.pkg.dev/cryptotrading-485110/cloud-run-source-deploy --include-tags --limit 5

# Deploy using latest tag
Write-Host ""
Write-Host "Deploying kraken-trader with Stage 2..." -ForegroundColor Yellow

gcloud run deploy kraken-trader `
  --project cryptotrading-485110 `
  --region australia-southeast1 `
  --image australia-southeast1-docker.pkg.dev/cryptotrading-485110/cloud-run-source-deploy/kraken-trader:latest `
  --platform managed `
  --allow-unauthenticated `
  --set-env-vars STAGE=stage2,SIMULATION_MODE=true