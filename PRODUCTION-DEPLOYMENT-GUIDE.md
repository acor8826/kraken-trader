# Production Deployment Guide - Kraken Trader

## Current Issues & Solutions

### 1. WebSocket Connection Failures on Cloud Run

**Issue**: Google Cloud Run has limited WebSocket support, causing connection failures.

**Solution Implemented**:
- Added automatic detection of production environment
- Dashboard falls back to polling when WebSocket is unavailable
- Polling interval: 5 seconds (configurable)

### 2. Cost Stats API Error

**Issue**: `"name 'llm' is not defined"` error in `/api/cost/stats` endpoint

**Solution**: Fixed reference to use `orchestrator.llm` instead of undefined `llm`

## Deployment Options

### Option A: Cloud Run with Polling (Current)
```bash
# Deploy with current configuration
./scripts/deploy_multi_timeframe.sh
```

**Pros**:
- Serverless, auto-scaling
- Cost-effective
- Easy deployment

**Cons**:
- No true WebSocket support
- 5-second delay for updates

### Option B: Cloud Run with Session Affinity (Experimental)
```bash
# Deploy with WebSocket support attempt
./scripts/deploy-with-websocket-support.sh
```

**Pros**:
- May support WebSocket with session affinity
- Still serverless

**Cons**:
- Limited reliability
- WebSocket may still disconnect

### Option C: Deploy to GKE (Full WebSocket Support)
```yaml
# kubernetes/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: kraken-trader
spec:
  replicas: 1
  selector:
    matchLabels:
      app: kraken-trader
  template:
    metadata:
      labels:
        app: kraken-trader
    spec:
      containers:
      - name: kraken-trader
        image: australia-southeast1-docker.pkg.dev/cryptotrading-485110/cloud-run-source-deploy/kraken-trader:latest
        ports:
        - containerPort: 8080
        env:
        - name: ENABLE_WEBSOCKET
          value: "true"
```

## How the Fix Works

### 1. Environment Detection
```javascript
// dashboard-config.js
isProduction: window.location.hostname.includes('run.app')
```

### 2. Automatic Fallback
- Production: Uses polling every 5 seconds
- Local: Uses WebSocket for real-time updates

### 3. Seamless Experience
- Users see the same UI regardless of connection method
- No manual configuration needed

## Testing

### Local Testing (WebSocket)
```bash
cd kraken-trader
.\start-server-fixed.ps1
# Open http://localhost:8080/dashboard/index.html
# Console: "[Dashboard Config] Environment: LOCAL"
```

### Production Testing (Polling)
```bash
# After deployment
# Open https://kraken-trader-709516859644.australia-southeast1.run.app/dashboard/index.html
# Console: "[Dashboard Config] Environment: PRODUCTION (Cloud Run)"
```

## Monitoring

Check the browser console for:
- `[Dashboard Config] WebSocket: DISABLED (using polling)`
- `[Polling] Started with 5000ms interval`
- No more WebSocket connection errors

## Future Improvements

1. **Reduce Polling Frequency**: Adjust based on trading activity
2. **Server-Sent Events**: One-way real-time updates that work on Cloud Run
3. **Migration to GKE**: For true WebSocket support if needed

## Quick Commands

```bash
# View logs
gcloud run logs read --service kraken-trader --region australia-southeast1

# Update environment variables
gcloud run services update kraken-trader --region australia-southeast1 --set-env-vars "KEY=value"

# Check service status
gcloud run services describe kraken-trader --region australia-southeast1
```