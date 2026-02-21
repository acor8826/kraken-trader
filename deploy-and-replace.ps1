#!/usr/bin/env pwsh
# Deploy new service and replace old one

Write-Host "==========================================="  -ForegroundColor Green
Write-Host "Deploy New Service & Delete Old"  -ForegroundColor Green
Write-Host "==========================================="  -ForegroundColor Green

# Configuration
$PROJECT_ID = "cryptotrading-485110"
$REGION = "australia-southeast1"
$OLD_SERVICE_NAME = "kraken-trader"
$NEW_SERVICE_NAME = "kraken-trader"  # Using same name after deleting old
$IMAGE_URL = "$REGION-docker.pkg.dev/$PROJECT_ID/cloud-run-source-deploy/${NEW_SERVICE_NAME}:latest"

# Verify correct project
Write-Host ""
Write-Host "Verifying project..." -ForegroundColor Yellow
$currentProject = gcloud config get-value project
if ($currentProject -ne $PROJECT_ID) {
    Write-Host "Setting correct project: $PROJECT_ID" -ForegroundColor Yellow
    gcloud config set project $PROJECT_ID
} else {
    Write-Host "Already in correct project: $PROJECT_ID" -ForegroundColor Green
}

# Step 1: Check if old service exists
Write-Host ""
Write-Host "Step 1: Checking existing service..." -ForegroundColor Yellow
$serviceExists = gcloud run services list --platform managed --region $REGION --format="value(name)" | Where-Object { $_ -eq $OLD_SERVICE_NAME }

if ($serviceExists) {
    Write-Host "Found existing service: $OLD_SERVICE_NAME" -ForegroundColor Green
    
    # Get old service URL for reference
    $oldUrl = gcloud run services describe $OLD_SERVICE_NAME --region $REGION --format="value(status.url)"
    Write-Host "Current URL: $oldUrl" -ForegroundColor Cyan
} else {
    Write-Host "No existing service found" -ForegroundColor Yellow
}

# Step 2: Build fresh image with all fixes
Write-Host ""
Write-Host "Step 2: Building fresh image with ALL fixes..." -ForegroundColor Yellow

gcloud builds submit `
  --project $PROJECT_ID `
  --region $REGION `
  --tag $IMAGE_URL `
  .

if ($LASTEXITCODE -ne 0) {
    Write-Host "Build failed!" -ForegroundColor Red
    exit 1
}

# Step 3: Delete old service if it exists
if ($serviceExists) {
    Write-Host ""
    Write-Host "Step 3: Deleting old service..." -ForegroundColor Yellow
    
    gcloud run services delete $OLD_SERVICE_NAME `
      --region $REGION `
      --quiet
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Old service deleted successfully" -ForegroundColor Green
    } else {
        Write-Host "Failed to delete old service" -ForegroundColor Red
        exit 1
    }
    
    # Wait a moment for deletion to complete
    Start-Sleep -Seconds 5
}

# Step 4: Deploy new service with correct configuration
Write-Host ""
Write-Host "Step 4: Deploying new service with Stage 2..." -ForegroundColor Yellow

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
  --set-env-vars "SIMULATION_MODE=true" `
  --set-env-vars "MULTI_TIMEFRAME_ENABLED=true" `
  --set-env-vars "CHECK_INTERVAL_MINUTES=15" `
  --set-env-vars "MIN_HOLD_TIME_HOURS=0.5" `
  --set-env-vars "USE_FALLBACK_VOLATILITY=true" `
  --set-env-vars "PRIMARY_TIMEFRAMES=15m,1h,4h"

if ($LASTEXITCODE -ne 0) {
    Write-Host "Deployment failed!" -ForegroundColor Red
    exit 1
}

# Step 5: Get new service URL
Write-Host ""
Write-Host "Step 5: Getting new service details..." -ForegroundColor Yellow

$newUrl = gcloud run services describe $NEW_SERVICE_NAME `
  --project $PROJECT_ID `
  --region $REGION `
  --format="value(status.url)"

# Step 6: Verify deployment
Write-Host ""
Write-Host "Step 6: Verifying deployment..." -ForegroundColor Yellow

# Test API status
try {
    $response = [System.Net.WebClient]::new().DownloadString("$newUrl/api/status")
    $json = $response | ConvertFrom-Json
    
    if ($json.stage -eq "stage2") {
        Write-Host "   [OK] Stage 2 confirmed!" -ForegroundColor Green
    } else {
        Write-Host "   ✗ Stage incorrect: $($json.stage)" -ForegroundColor Red
    }
    
    Write-Host "   ✓ API responding" -ForegroundColor Green
} catch {
    Write-Host "   ✗ API Error: $_" -ForegroundColor Red
}

# Summary
Write-Host ""
Write-Host "==========================================="  -ForegroundColor Green
Write-Host "Deployment Complete!"  -ForegroundColor Green
Write-Host "==========================================="  -ForegroundColor Green
Write-Host ""
Write-Host "Service: $NEW_SERVICE_NAME" -ForegroundColor Cyan
Write-Host "Project: $PROJECT_ID" -ForegroundColor Cyan
Write-Host "Region: $REGION" -ForegroundColor Cyan
Write-Host "URL: $newUrl" -ForegroundColor Cyan
Write-Host "Dashboard: $newUrl/dashboard/index.html" -ForegroundColor Cyan
Write-Host ""
Write-Host "All fixes included:" -ForegroundColor Green
Write-Host "  ✓ WebSocket to polling fallback" -ForegroundColor Green
Write-Host "  ✓ Cost stats API fix" -ForegroundColor Green
Write-Host "  ✓ Multi-timeframe calculations" -ForegroundColor Green
Write-Host "  ✓ Stage 2 configuration" -ForegroundColor Green
Write-Host ""
if ($serviceExists -and $oldUrl) {
    Write-Host "Old service deleted: $oldUrl" -ForegroundColor Yellow
}
Write-Host "New service active: $newUrl" -ForegroundColor Green
