# Stage 1: the React build
FROM node:22-alpine AS frontend
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: development and tests on Linux, the same on Mac and Windows (docker compose run --rm dev).
# The repo is bind-mounted at /app; the virtualenv lives in /opt/venv so it never touches a host .venv.
FROM python:3.12-slim AS dev
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/* \
    && git config --system --add safe.directory /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_PYTHON=3.12 UV_PYTHON_DOWNLOADS=never UV_FROZEN=1 UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH" PYTHONPATH=/app PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock ./
RUN uv sync

# Stage 3: the API, serving the build at /
FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY src/ ./src/
COPY data/fixtures/ ./data/fixtures/
COPY supabase/ ./supabase/
COPY --from=frontend /ui/dist ./frontend/dist
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH="/app" APP_ENV=production \
    LAKEHOUSE_PATH=data/lakehouse.duckdb OPS_DB_PATH=data/ops.duckdb
# Production by default: the image issues no local tokens and needs SUPABASE_URL to start.
# docker-compose.yml sets APP_ENV=development for local use.
# Mount the lakehouse (git-ignored, built from S3) at /app/data/lakehouse.duckdb; the ops store is created on first use.
VOLUME ["/app/data"]
EXPOSE 8000
CMD ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
