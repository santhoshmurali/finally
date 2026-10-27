#!/usr/bin/env bash
# Stops FinAlly and removes its container and image. The finally-data volume is kept.
# Usage: ./scripts/stop_mac.sh
set -eo pipefail

IMAGE_NAME=finally
CONTAINER_NAME=finally-app

if ! docker info >/dev/null 2>&1; then
    echo "Docker is not running, so there is nothing to stop."
    exit 0
fi

docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
docker image rm "$IMAGE_NAME" >/dev/null 2>&1 || true
docker image prune -f --filter 'label=finally.project=finally' >/dev/null 2>&1 || true
echo "FinAlly stopped. Data in the finally-data volume is kept."
