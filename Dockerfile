# Stage 1: build the Next.js static export
FROM node:20-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python runtime with the FastAPI backend and the static export
FROM python:3.12-slim
LABEL finally.project=finally
COPY --from=ghcr.io/astral-sh/uv:0.12.12 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    FINALLY_DB_PATH=/app/db/finally.db \
    FINALLY_STATIC_DIR=/app/static \
    UV_HTTP_RETRIES=10 \
    UV_HTTP_TIMEOUT=120

WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-install-project --no-default-groups

COPY backend/ ./
RUN uv sync --frozen --no-default-groups

COPY --from=frontend-build /app/frontend/out /app/static
RUN mkdir -p /app/db

VOLUME ["/app/db"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["/app/backend/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health', timeout=4)"]

CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
