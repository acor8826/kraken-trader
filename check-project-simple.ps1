#!/usr/bin/env pwsh
# Check current GCloud project

$currentProject = gcloud config get-value project
$targetProject = "cryptotrading-485110"

Write-Host "Current project: $currentProject"
Write-Host "Target project: $targetProject"

if ($currentProject -eq $targetProject) {
    Write-Host "Correct project selected!" -ForegroundColor Green
} else {
    Write-Host "Wrong project! Switch with: gcloud config set project $targetProject" -ForegroundColor Red
}

Write-Host ""
Write-Host "Services in $targetProject region australia-southeast1:"
gcloud run services list --platform managed --region australia-southeast1