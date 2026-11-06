#!/usr/bin/env bash
# Build the FinAlly image if needed and start the container on http://localhost:8000.
# Usage: scripts/start_mac.sh [--build] [--open]
set -euo pipefail

IMAGE=finally
CONTAINER=finally
PORT=8000
URL="http://localhost:${PORT}"

build=false
open_browser=false
for arg in "$@"; do
  case "$arg" in
    --build) build=true ;;
    --open) open_browser=true ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "Missing .env. Copy .env.example to .env and fill it in." >&2
  exit 1
fi

if [ "$build" = true ] || [ -z "$(docker images -q "$IMAGE")" ]; then
  docker build -t "$IMAGE" .
fi

docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
docker run -d --name "$CONTAINER" -p "$PORT:8000" --env-file .env \
  -v finally-data:/app/db --restart unless-stopped "$IMAGE" >/dev/null

echo "FinAlly is running at $URL"

if [ "$open_browser" = true ]; then
  if command -v open >/dev/null 2>&1; then open "$URL"; elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"; fi
fi
