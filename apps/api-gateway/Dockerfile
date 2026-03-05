# =============================================================================
# Arachne API Gateway — Multi-stage Dockerfile
# =============================================================================
# Multi-stage build:
#   1. Builder: install dependencies with uv (fast, cached)
#   2. Runtime: slim image with only production dependencies
# =============================================================================

FROM python:3.13-slim AS builder

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files first (Docker layer caching)
COPY apps/api-gateway/pyproject.toml ./apps/api-gateway/
COPY packages/core-models/pyproject.toml ./packages/core-models/
COPY packages/messaging/pyproject.toml ./packages/messaging/
COPY packages/storage/pyproject.toml ./packages/storage/

# Copy source for local package installs
COPY packages/core-models/ ./packages/core-models/
COPY packages/messaging/ ./packages/messaging/
COPY packages/storage/ ./packages/storage/
COPY apps/api-gateway/ ./apps/api-gateway/

# Install all dependencies
RUN uv pip install --system --no-cache \
    -e ./packages/core-models \
    -e ./packages/messaging \
    -e ./packages/storage \
    -e ./apps/api-gateway

# =============================================================================
# Runtime stage
# =============================================================================
FROM python:3.13-slim

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application source
COPY apps/api-gateway/src/ ./src/
COPY packages/core-models/src/ ./packages/core-models/src/
COPY packages/core-models/alembic/ ./alembic/
COPY packages/core-models/alembic.ini ./alembic.ini

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')"

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
