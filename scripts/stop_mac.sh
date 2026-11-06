#!/usr/bin/env bash
# Stop and remove the FinAlly container and image. The finally-data volume is kept.
set -euo pipefail

docker rm -f finally >/dev/null 2>&1 || true
docker rmi finally >/dev/null 2>&1 || true

echo "FinAlly stopped. Data volume finally-data was kept."
