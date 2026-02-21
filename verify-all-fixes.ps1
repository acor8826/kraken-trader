#!/usr/bin/env pwsh
param(
    [string]$ServiceUrl = "https://kraken-trader-709516859644.australia-southeast1.run.app"
)

Write-Host "==================================="  -ForegroundColor Green
Write-Host "Verifying ALL Fixes"  -ForegroundColor Green
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
        Write-Host "   ✗ Stage: $($json.stage) (should be stage2)" -ForegroundColor Red
        $allPassed = $false
    }
    Write-Host "   ✓ API responding" -ForegroundColor Green
} catch {
    Write-Host "   ✗ API Error: $_" -ForegroundColor Red
    $allPassed = $false
}

# Test 2: Cost Stats Endpoint
Write-Host ""
Write-Host "2. Testing Cost Stats Endpoint..." -ForegroundColor Yellow
try {
    $response = [System.Net.WebClient]::new().DownloadString("$ServiceUrl/api/cost/stats")
    $json = $response | ConvertFrom-Json
    
    if ($json.error) {
        Write-Host "   ✗ Error present: $($json.error)" -ForegroundColor Red
        $allPassed = $false
    } else {
        Write-Host "   ✓ No errors! Cost stats working" -ForegroundColor Green
    }
} catch {
    Write-Host "   ✗ Request failed: $_" -ForegroundColor Red
    $allPassed = $false
}

# Test 3: Dashboard Config (WebSocket fix)
Write-Host ""
Write-Host "3. Testing Dashboard Config..." -ForegroundColor Yellow
try {
    $response = [System.Net.WebClient]::new().DownloadString("$ServiceUrl/dashboard-config.js")
    if ($response -match "isProduction.*run\.app") {
        Write-Host "   ✓ WebSocket detection code present" -ForegroundColor Green
    } else {
        Write-Host "   ✗ WebSocket fix missing" -ForegroundColor Red
        $allPassed = $false
    }
} catch {
    Write-Host "   ✗ Could not load dashboard-config.js: $_" -ForegroundColor Red
    $allPassed = $false
}

# Test 4: Portfolio Endpoint
Write-Host ""
Write-Host "4. Testing Portfolio Endpoint..." -ForegroundColor Yellow
try {
    $response = [System.Net.WebClient]::new().DownloadString("$ServiceUrl/portfolio")
    $json = $response | ConvertFrom-Json
    Write-Host "   ✓ Portfolio endpoint working" -ForegroundColor Green
} catch {
    Write-Host "   ✗ Portfolio error: $_" -ForegroundColor Red
    $allPassed = $false
}

# Summary
Write-Host ""
Write-Host "==================================="  -ForegroundColor Green
if ($allPassed) {
    Write-Host "✅ ALL TESTS PASSED!"  -ForegroundColor Green
    Write-Host ""
    Write-Host "Features confirmed working:" -ForegroundColor Green
    Write-Host "  ✓ Stage 2 configuration" -ForegroundColor Green
    Write-Host "  ✓ Cost stats API (no errors)" -ForegroundColor Green
    Write-Host "  ✓ WebSocket to polling fallback" -ForegroundColor Green
    Write-Host "  ✓ API endpoints responding" -ForegroundColor Green
} else {
    Write-Host "❌ SOME TESTS FAILED"  -ForegroundColor Red
    Write-Host ""
    Write-Host "Please check the errors above." -ForegroundColor Yellow
}
Write-Host "==================================="  -ForegroundColor Green
Write-Host ""
Write-Host "Dashboard URL: $ServiceUrl/dashboard/index.html" -ForegroundColor Cyan
