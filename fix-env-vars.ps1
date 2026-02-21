#!/usr/bin/env pwsh
Write-Host "Fixing environment variables..." -ForegroundColor Green

# Use the working revision 00050-fxd as base and update env vars properly
gcloud run services update kraken-trader `
  --project cryptotrading-485110 `
  --region australia-southeast1 `
  --image australia-southeast1-docker.pkg.dev/cryptotrading-485110/cloud-run-source-deploy/kraken-trader@sha256:b4ae4c7b8cfab32ecca06ca701eec972260a7d83fa8c9c21b04b151e41a95811 `
  --clear-env-vars `
  --set-env-vars "STAGE=stage2" `
  --set-env-vars "SIMULATION_MODE=true" `
  --set-env-vars "MULTI_TIMEFRAME_ENABLED=true" `
  --set-env-vars "CHECK_INTERVAL_MINUTES=15"

Write-Host "Environment variables fixed!" -ForegroundColor Green