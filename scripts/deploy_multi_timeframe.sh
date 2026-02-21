#!/bin/bash
# Deploy Kraken Trader with Multi-Timeframe Analysis

echo "Deploying Kraken Trader with Multi-Timeframe Analysis..."

# Build and deploy
gcloud builds submit --tag australia-southeast1-docker.pkg.dev/cryptotrading-485110/cloud-run-source-deploy/kraken-trader:latest .

gcloud run deploy kraken-trader   --image australia-southeast1-docker.pkg.dev/cryptotrading-485110/cloud-run-source-deploy/kraken-trader:latest   --platform managed   --region australia-southeast1   --set-env-vars "MULTI_TIMEFRAME_ENABLED=true,CHECK_INTERVAL_MINUTES=15,MIN_HOLD_TIME_HOURS=0.5,USE_FALLBACK_VOLATILITY=true,PRIMARY_TIMEFRAMES=15m,1h,4h"   --memory 512Mi   --cpu 1   --timeout 300   --max-instances 1   --allow-unauthenticated

echo "Deployment complete!"
