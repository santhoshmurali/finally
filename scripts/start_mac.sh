#!/usr/bin/env bash
# Starts FinAlly in Docker at http://localhost:8000. Safe to run more than once.
# Usage: ./scripts/start_mac.sh [--build] [--open]
set -eo pipefail

IMAGE_NAME=finally
CONTAINER_NAME=finally-app
VOLUME_NAME=finally-data
URL=http://localhost:8000
STARTUP_WAIT_SECONDS=10

BUILD=false
OPEN=false
for arg in "$@"; do
    case "$arg" in
        --build) BUILD=true ;;
        --open) OPEN=true ;;
        *) echo "Unknown option: $arg" >&2; exit 1 ;;
    esac
done

cd "$(dirname "$0")/.."

if ! docker info >/dev/null 2>&1; then
    echo "Docker is not running. Start Docker and try again." >&2
    exit 1
fi

if [[ "$BUILD" == true || -z "$(docker image ls -q "$IMAGE_NAME")" ]]; then
    docker build -t "$IMAGE_NAME" .
    docker image prune -f --filter 'label=finally.project=finally' >/dev/null
fi

# Replace any previous container; the named volume is never touched.
docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true

ENV_ARGS=()
if [[ -f .env ]]; then
    ENV_ARGS=(--env-file .env)
fi

docker run -d --name "$CONTAINER_NAME" -p 8000:8000 -v "$VOLUME_NAME:/app/db" \
    "${ENV_ARGS[@]}" "$IMAGE_NAME" >/dev/null

# A bad configuration (for example an expired Dhan token) makes the app exit within seconds.
RUNNING=true
for _ in $(seq "$STARTUP_WAIT_SECONDS"); do
    sleep 1
    RUNNING=$(docker inspect -f '{{.State.Running}}' "$CONTAINER_NAME")
    [[ "$RUNNING" == true ]] || break
done
if [[ "$RUNNING" != true ]]; then
    docker logs --tail 10 "$CONTAINER_NAME" 2>&1
    echo "FinAlly exited on startup. The log lines above show why." >&2
    exit 1
fi

echo "FinAlly is starting at $URL"
if [[ "$OPEN" == true ]]; then
    if command -v open >/dev/null 2>&1; then
        open "$URL"
    elif command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$URL"
    fi
fi
