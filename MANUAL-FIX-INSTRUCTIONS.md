# Manual Fix Instructions - Kraken Trader Stage 2 Deployment

## Issue
Container import is failing when deploying via gcloud CLI. This appears to be a Cloud Run platform issue.

## Solution: Use Google Cloud Console

### Step 1: Access Cloud Console
1. Go to: https://console.cloud.google.com/run
2. Select project: `cryptotrading-485110`
3. Select region: `australia-southeast1`

### Step 2: Delete Failed Service (if exists)
1. Find `kraken-trader` in the services list
2. Click the checkbox next to it
3. Click "DELETE" at the top
4. Confirm deletion

### Step 3: Create New Service
1. Click "CREATE SERVICE"
2. Select "Continuously deploy new revisions from a source repository"
3. Click "SET UP WITH CLOUD BUILD"

### Step 4: Configure Source
1. Repository provider: GitHub
2. Repository: `acor8826/kraken-trader`
3. Branch: `^master$`
4. Build Type: Dockerfile
5. Source location: `/`

### Step 5: Configure Service
1. Service name: `kraken-trader`
2. Region: `australia-southeast1`
3. CPU allocation: "CPU is only allocated during request processing"
4. Minimum instances: 0
5. Maximum instances: 5
6. Memory: 512 MiB
7. CPU: 1
8. Request timeout: 300 seconds
9. Authentication: "Allow unauthenticated invocations"

### Step 6: Environment Variables
Click "VARIABLES & SECRETS" tab and add:
- `STAGE` = `stage2`
- `SIMULATION_MODE` = `true`
- `MULTI_TIMEFRAME_ENABLED` = `true`
- `CHECK_INTERVAL_MINUTES` = `15`
- `MIN_HOLD_TIME_HOURS` = `0.5`
- `USE_FALLBACK_VOLATILITY` = `true`
- `PRIMARY_TIMEFRAMES` = `15m,1h,4h`

### Step 7: Deploy
1. Click "CREATE"
2. Wait for deployment to complete

## Alternative: Use Existing Working Image

If the above fails, try deploying with the last known working image:

1. Click "CREATE SERVICE"
2. Select "Deploy one revision from an existing container image"
3. Container image URL: 
   ```
   australia-southeast1-docker.pkg.dev/cryptotrading-485110/cloud-run-source-deploy/kraken-trader@sha256:b4ae4c7b8cfab32ecca06ca701eec972260a7d83fa8c9c21b04b151e41a95811
   ```
4. Follow steps 5-7 above for configuration

## Expected Result
Once deployed, you should have:
- Service URL: `https://kraken-trader-709516859644.australia-southeast1.run.app`
- Dashboard URL: `https://kraken-trader-709516859644.australia-southeast1.run.app/dashboard/index.html`

## Verify Deployment
Check that:
1. API Status shows `stage2`: https://kraken-trader-709516859644.australia-southeast1.run.app/api/status
2. No WebSocket errors in dashboard console
3. Cost stats endpoint works without errors

## All Fixes Included
The deployed service includes:
- ✅ WebSocket to polling fallback
- ✅ Cost stats API fix  
- ✅ Multi-timeframe calculations
- ✅ Stage 2 configuration