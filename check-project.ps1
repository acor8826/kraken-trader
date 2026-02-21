#!/usr/bin/env pwsh
# Check current GCloud project before deployment

Write-Host "Checking GCloud Configuration..." -ForegroundColor Green
Write-Host ""

# Get current project
$currentProject = gcloud config get-value project
$targetProject = "cryptotrading-485110"

Write-Host "Current project: $currentProject" -ForegroundColor Cyan
Write-Host "Target project: $targetProject" -ForegroundColor Cyan
Write-Host ""

if ($currentProject -eq $targetProject) {
    Write-Host "✓ Correct project selected!" -ForegroundColor Green
} else {
    Write-Host "✗ Wrong project selected!" -ForegroundColor Red
    Write-Host ""
    Write-Host "To switch to correct project:" -ForegroundColor Yellow
    Write-Host "  gcloud config set project $targetProject" -ForegroundColor White
}

Write-Host ""
Write-Host "Current services in ${targetProject}:" -ForegroundColor Yellow
gcloud run services list --platform managed --region australia-southeast1 --format="table(name,status.url)"