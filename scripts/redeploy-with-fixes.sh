#!/bin/bash
# Redeploy Kraken Trader with production fixes

echo "==================================="
echo "Redeploying Kraken Trader with fixes"
echo "==================================="

# Configuration
PROJECT_ID="cryptotrading-485110"
REGION="australia-southeast1"
SERVICE_NAME="kraken-trader"

echo "1. Building new container with fixes..."
gcloud builds submit \
  --project $PROJECT_ID \
  --region $REGION \
  --tag $REGION-docker.pkg.dev/$PROJECT_ID/cloud-run-source-deploy/$SERVICE_NAME:latest \
  .

echo ""
echo "2. Deploying to Cloud Run..."
gcloud run deploy $SERVICE_NAME \
  --project $PROJECT_ID \
  --region $REGION \
  --image $REGION-docker.pkg.dev/$PROJECT_ID/cloud-run-source-deploy/$SERVICE_NAME:latest \
  --platform managed \
  --memory 512Mi \
  --cpu 1 \
  --timeout 300 \
  --max-instances 5 \
  --allow-unauthenticated

echo ""
echo "3. Getting service URL..."
SERVICE_URL=$(gcloud run services describe $SERVICE_NAME --project $PROJECT_ID --region $REGION --format='value(status.url)')

echo ""
echo "==================================="
echo "Deployment complete!"
echo "==================================="
echo "Dashboard URL: $SERVICE_URL/dashboard/index.html"
echo ""
echo "The dashboard will automatically use polling instead of WebSocket on Cloud Run."
echo "Check browser console for: [Dashboard Config] Environment: PRODUCTION (Cloud Run)"