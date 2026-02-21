#!/usr/bin/env pwsh
# Deploy cost stats fix

Write-Host "Deploying cost stats fix..." -ForegroundColor Yellow

# Quick deploy using existing image with just the code change
gcloud run deploy kraken-trader `
  --project cryptotrading-485110 `
  --region australia-southeast1 `
  --source . `
  --platform managed

Write-Host "Fix deployed! The cost stats endpoint should now work properly." -ForegroundColor Green