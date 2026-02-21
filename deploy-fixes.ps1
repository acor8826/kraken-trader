#!/usr/bin/env pwsh
# Deploy Kraken Trader fixes to Google Cloud Run

Write-Host "==================================="  -ForegroundColor Green
Write-Host "Deploying Kraken Trader with fixes"  -ForegroundColor Green
Write-Host "==================================="  -ForegroundColor Green

# Configuration
$PROJECT_ID = "cryptotrading-485110"
$REGION = "australia-southeast1"
$SERVICE_NAME = "kraken-trader"
$IMAGE_URL = "$REGION-docker.pkg.dev/$PROJECT_ID/cloud-run-source-deploy/${SERVICE_NAME}:latest"

Write-Host ""
Write-Host "1. Building new container with fixes..." -ForegroundColor Yellow

# Build container
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
Write-Host "2. Deploying to Cloud Run..." -ForegroundColor Yellow

# Deploy to Cloud Run
gcloud run deploy $SERVICE_NAME `
  --project $PROJECT_ID `
  --region $REGION `
  --image $IMAGE_URL `
  --platform managed `
  --memory 512Mi `
  --cpu 1 `
  --timeout 300 `
  --max-instances 5 `
  --allow-unauthenticated

if ($LASTEXITCODE -ne 0) {
    Write-Host "Deployment failed!" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "3. Getting service URL..." -ForegroundColor Yellow

# Get service URL
$SERVICE_URL = gcloud run services describe $SERVICE_NAME `
  --project $PROJECT_ID `
  --region $REGION `
  --format="value(status.url)"

Write-Host ""
Write-Host "==================================="  -ForegroundColor Green
Write-Host "Deployment complete!"  -ForegroundColor Green
Write-Host "==================================="  -ForegroundColor Green
Write-Host "Dashboard URL: $SERVICE_URL/dashboard/index.html" -ForegroundColor Cyan
Write-Host ""
Write-Host "The dashboard will automatically use polling instead of WebSocket on Cloud Run." -ForegroundColor Yellow
Write-Host "Check browser console for: [Dashboard Config] Environment: PRODUCTION (Cloud Run)" -ForegroundColor Yellow