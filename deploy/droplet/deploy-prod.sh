#!/bin/bash
#
# Deploy UCFP to a production droplet.
#
# Prerequisites:
#   - Docker running locally
#   - The droplet image built and saved to the tar this script ships:
#       docker build -f deploy/droplet/Dockerfile --platform linux/amd64 \
#           -t ucfp:$(cat VERSION) -t ucfp:latest .
#       docker save ucfp:$(cat VERSION) | gzip > /tmp/ucfp-docker-image-$(cat VERSION).tar.gz
#   - The host provisioned once (deploy/droplet/do-droplet-init.sh)
#   - SSH access to the production droplet configured
#
# Per-project: set DEPLOY_HOST and the verify domain below to your droplet.
#

set -e  # Exit on first error

# Configuration  (per-project — edit these)
DEPLOY_HOST="root@example.com"
DEPLOY_PATH="/opt/ucfp"
UCFP_VERSION=$(cat VERSION)
IMAGE_FILE="/tmp/ucfp-docker-image-${UCFP_VERSION}.tar.gz"

echo "=== Deploying UCFP ${UCFP_VERSION} to production ==="

# Pre-flight checks
echo "Checking prerequisites..."

if ! docker info > /dev/null 2>&1; then
    echo "ERROR: Docker is not running. Please start Docker and try again."
    exit 1
fi

if [ ! -f "$IMAGE_FILE" ]; then
    echo "ERROR: Docker image not found at ${IMAGE_FILE}"
    echo "       Build and save it first (see the header comment)."
    exit 1
fi

if [ ! -f ".private/env/docker-compose.production.env" ]; then
    echo "ERROR: Production environment file not found."
    echo "       Generate it: make .private/env/docker-compose.production.env"
    exit 1
fi

# Copy deployment files to droplet
echo "Copying deployment files to droplet..."
scp .private/env/docker-compose.production.env "${DEPLOY_HOST}:${DEPLOY_PATH}/ucfp.env"
scp .private/env/production.sh "${DEPLOY_HOST}:${DEPLOY_PATH}/ucfp.sh"
scp deploy/droplet/docker-compose.production.yml "${DEPLOY_HOST}:${DEPLOY_PATH}/docker-compose.yml"

# Copy Docker image to droplet
echo "Copying Docker image to droplet (this may take a minute)..."
scp "$IMAGE_FILE" "${DEPLOY_HOST}:/tmp/"

# Load image and restart services on droplet
echo "Loading image and restarting services on droplet..."
ssh "$DEPLOY_HOST" "
    set -e
    gunzip -c /tmp/ucfp-docker-image-${UCFP_VERSION}.tar.gz | docker load
    cd ${DEPLOY_PATH}
    UCFP_VERSION=${UCFP_VERSION} docker-compose --env-file ucfp.env down || true
    UCFP_VERSION=${UCFP_VERSION} docker-compose --env-file ucfp.env up -d
    rm /tmp/ucfp-docker-image-${UCFP_VERSION}.tar.gz
"

echo ""
echo "=== Deployment complete! ==="
echo ""
echo "Verify the deployment:"
echo "  curl -I https://example.com"
echo "  ssh ${DEPLOY_HOST} 'docker ps'"
echo ""

# Prompt to clean up local temp file
IMAGE_SIZE=$(du -h "$IMAGE_FILE" | cut -f1)
read -p "Remove local image file ${IMAGE_FILE} (${IMAGE_SIZE})? [y/N] " -n 1 -r || true
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm "$IMAGE_FILE"
    echo "Removed."
else
    echo "Keeping ${IMAGE_FILE}"
fi
