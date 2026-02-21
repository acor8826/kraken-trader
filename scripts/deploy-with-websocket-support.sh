#!/bin/bash
# Deploy Kraken Trader with WebSocket support (limited on Cloud Run)

echo "Deploying Kraken Trader with WebSocket support configuration..."

PROJECT_ID="cryptotrading-485110"
REGION="australia-southeast1"
SERVICE_NAME="kraken-trader"
IMAGE_URL="$REGION-docker.pkg.dev/$PROJECT_ID/cloud-run-source-deploy/$SERVICE_NAME:latest"

# Build the container
echo "Building container..."
gcloud builds submit --tag $IMAGE_URL .

# Deploy with WebSocket-friendly settings
echo "Deploying to Cloud Run with WebSocket configuration..."
gcloud run deploy $SERVICE_NAME \
  --image $IMAGE_URL \
  --platform managed \
  --region $REGION \
  --memory 512Mi \
  --cpu 1 \
  --timeout 3600 \
  --max-instances 10 \
  --min-instances 1 \
  --concurrency 1000 \
  --allow-unauthenticated \
  --session-affinity \
  --cpu-boost \
  --set-env-vars "STAGE=stage1,SIMULATION_MODE=false,ENABLE_WEBSOCKET=true,CHECK_INTERVAL_MINUTES=15"

echo "Deployment complete!"
echo ""
echo "NOTE: WebSocket support on Cloud Run is limited. The dashboard will fall back to polling."
echo "For full WebSocket support, consider deploying to GKE or Compute Engine."