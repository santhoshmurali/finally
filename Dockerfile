# syntax=docker/dockerfile:1

# Stage 1: build the Next.js frontend as a static export.
FROM node:20-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python runtime with the FastAPI backend and the static frontend.
FROM python:3.12-slim AS backend
# Lets scripts/stop_windows.ps1 find the superseded images left by rebuilds.
LABEL app="finally"
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/backend/.venv/bin:$PATH"

WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --locked --no-dev --no-default-groups --no-install-project

COPY backend/ ./
RUN uv sync --locked --no-dev --no-default-groups

COPY --from=frontend /app/frontend/out /app/static

ENV FINALLY_DB_PATH=/app/db/finally.db \
    FINALLY_STATIC_DIR=/app/static
RUN mkdir -p /app/db

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
