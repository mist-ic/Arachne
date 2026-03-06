# =============================================================================
# Arachne HTTP Worker — Multi-stage Dockerfile
# =============================================================================

FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files (layer caching)
COPY apps/worker-http/pyproject.toml ./apps/worker-http/
COPY packages/core-models/pyproject.toml ./packages/core-models/
COPY packages/messaging/pyproject.toml ./packages/messaging/
COPY packages/storage/pyproject.toml ./packages/storage/
COPY packages/anti-detection/pyproject.toml ./packages/anti-detection/

# Copy source for local packages
COPY packages/core-models/ ./packages/core-models/
COPY packages/messaging/ ./packages/messaging/
COPY packages/storage/ ./packages/storage/
COPY packages/anti-detection/ ./packages/anti-detection/
COPY apps/worker-http/ ./apps/worker-http/

# Install all dependencies
RUN uv pip install --system --no-cache \
    -e ./packages/core-models \
    -e ./packages/messaging \
    -e ./packages/storage \
    -e ./packages/anti-detection \
    -e ./apps/worker-http

# =============================================================================
# Runtime
# =============================================================================
FROM python:3.13-slim

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application and package source
COPY apps/worker-http/src/ ./src/
COPY packages/core-models/src/ ./packages/core-models/src/
COPY packages/messaging/src/ ./packages/messaging/src/
COPY packages/storage/src/ ./packages/storage/src/
COPY packages/anti-detection/src/ ./packages/anti-detection/src/

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app/src

CMD ["python", "-c", "from main import main; import asyncio; asyncio.run(main())"]
