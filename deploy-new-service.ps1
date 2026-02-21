#!/usr/bin/env pwsh
# Deploy as new service to bypass container import issues

Write-Host "==================================="  -ForegroundColor Green
Write-Host "Deploying as NEW SERVICE with ALL fixes"  -ForegroundColor Green
Write-Host "==================================="  -ForegroundColor Green

$PROJECT_ID = "cryptotrading-485110"
$REGION = "australia-southeast1"
$NEW_SERVICE_NAME = "kraken-trader-v2"
$IMAGE_URL = "$REGION-docker.pkg.dev/$PROJECT_ID/cloud-run-source-deploy/kraken-trader:latest"

Write-Host ""
Write-Host "1. Building fresh image with all fixes..." -ForegroundColor Yellow

# Build new image
gcloud builds submit `
  --project $PROJECT_ID `
  --region $REGION `
  --tag $IMAGE_URL `
  .

if ($LASTEXITCODE -ne 0) {
    Write-Host "Build failed!" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "2. Deploying as new service: $NEW_SERVICE_NAME" -ForegroundColor Yellow

# Deploy as new service with proper env vars
gcloud run deploy $NEW_SERVICE_NAME `
  --project $PROJECT_ID `
  --region $REGION `
  --image $IMAGE_URL `
  --platform managed `
  --memory 512Mi `
  --cpu 1 `
  --timeout 300 `
  --max-instances 5 `
  --allow-unauthenticated `
  --set-env-vars "STAGE=stage2" `
  --add-env-vars "SIMULATION_MODE=true" `
  --add-env-vars "MULTI_TIMEFRAME_ENABLED=true" `
  --add-env-vars "CHECK_INTERVAL_MINUTES=15" `
  --add-env-vars "MIN_HOLD_TIME_HOURS=0.5" `
  --add-env-vars "USE_FALLBACK_VOLATILITY=true" `
  --add-env-vars "PRIMARY_TIMEFRAMES=15m,1h,4h"

if ($LASTEXITCODE -ne 0) {
    Write-Host "Deployment failed!" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "3. Getting service URL..." -ForegroundColor Yellow

$SERVICE_URL = gcloud run services describe $NEW_SERVICE_NAME `
  --project $PROJECT_ID `
  --region $REGION `
  --format="value(status.url)"

Write-Host ""
Write-Host "==================================="  -ForegroundColor Green
Write-Host "Deployment Complete!"  -ForegroundColor Green
Write-Host "==================================="  -ForegroundColor Green
Write-Host ""
Write-Host "New Service URL: $SERVICE_URL" -ForegroundColor Cyan
Write-Host "Dashboard: $SERVICE_URL/dashboard/index.html" -ForegroundColor Cyan
Write-Host ""
Write-Host "Includes ALL fixes:" -ForegroundColor Green
Write-Host "  ✓ WebSocket to polling fallback" -ForegroundColor Green
Write-Host "  ✓ Cost stats API fix" -ForegroundColor Green
Write-Host "  ✓ Multi-timeframe calculations" -ForegroundColor Green
Write-Host "  ✓ Stage 2 configuration" -ForegroundColor Green
Write-Host ""
Write-Host "To switch traffic from old to new service:" -ForegroundColor Yellow
Write-Host "  1. Test new service thoroughly" -ForegroundColor White
Write-Host "  2. Update DNS/links to point to new URL" -ForegroundColor White
Write-Host "  3. Delete old service when ready" -ForegroundColor White