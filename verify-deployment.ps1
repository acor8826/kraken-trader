#!/usr/bin/env pwsh
param(
    [string]$ServiceUrl = "https://kraken-trader-709516859644.australia-southeast1.run.app"
)

Write-Host "==================================="  -ForegroundColor Green
Write-Host "Verifying Deployment"  -ForegroundColor Green
Write-Host "==================================="  -ForegroundColor Green
Write-Host "Service URL: $ServiceUrl" -ForegroundColor Cyan
Write-Host ""

$allPassed = $true

# Test 1: API Status
Write-Host "1. Testing API Status..." -ForegroundColor Yellow
try {
    $response = [System.Net.WebClient]::new().DownloadString("$ServiceUrl/api/status")
    $json = $response | ConvertFrom-Json
    
    if ($json.stage -eq "stage2") {
        Write-Host "   [OK] Stage: stage2 (correct!)" -ForegroundColor Green
    } else {
        Write-Host "   [FAIL] Stage: $($json.stage) (should be stage2)" -ForegroundColor Red
        $allPassed = $false
    }
    Write-Host "   [OK] API responding" -ForegroundColor Green
} catch {
    Write-Host "   [FAIL] API Error: $_" -ForegroundColor Red
    $allPassed = $false
}

# Test 2: Cost Stats Endpoint  
Write-Host ""
Write-Host "2. Testing Cost Stats Endpoint..." -ForegroundColor Yellow
try {
    $response = [System.Net.WebClient]::new().DownloadString("$ServiceUrl/api/cost/stats")
    $json = $response | ConvertFrom-Json
    
    if ($json.error) {
        Write-Host "   [FAIL] Error present: $($json.error)" -ForegroundColor Red
        $allPassed = $false
    } else {
        Write-Host "   [OK] No errors! Cost stats working" -ForegroundColor Green
    }
} catch {
    Write-Host "   [FAIL] Request failed: $_" -ForegroundColor Red
    $allPassed = $false
}

# Summary
Write-Host ""
Write-Host "==================================="  -ForegroundColor Green
if ($allPassed) {
    Write-Host "[PASS] ALL TESTS PASSED!"  -ForegroundColor Green
} else {
    Write-Host "[FAIL] SOME TESTS FAILED"  -ForegroundColor Red
}
Write-Host "==================================="  -ForegroundColor Green
Write-Host ""
Write-Host "Dashboard URL: $ServiceUrl/dashboard/index.html" -ForegroundColor Cyan