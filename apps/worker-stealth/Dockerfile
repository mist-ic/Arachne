# =============================================================================
# Arachne Stealth Worker — Multi-stage Dockerfile
# =============================================================================
# Includes browser dependencies (Chromium for Pydoll, Firefox via Camoufox)
# for stealth browser-based fetching. Significantly larger than worker-http.

FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install browser dependencies for Camoufox and Pydoll
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Chromium dependencies (for Pydoll)
    chromium \
    # Firefox dependencies (for Camoufox — installs its own binary)
    libgtk-3-0 \
    libdbus-glib-1-2 \
    libxt6 \
    libx11-xcb1 \
    libasound2 \
    # Virtual display for "headful headless" mode
    xvfb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency files (layer caching)
COPY apps/worker-stealth/pyproject.toml ./apps/worker-stealth/
COPY packages/core-models/pyproject.toml ./packages/core-models/
COPY packages/messaging/pyproject.toml ./packages/messaging/
COPY packages/storage/pyproject.toml ./packages/storage/
COPY packages/anti-detection/pyproject.toml ./packages/anti-detection/

# Copy source for local packages
COPY packages/core-models/ ./packages/core-models/
COPY packages/messaging/ ./packages/messaging/
COPY packages/storage/ ./packages/storage/
COPY packages/anti-detection/ ./packages/anti-detection/
COPY apps/worker-stealth/ ./apps/worker-stealth/

# Install all dependencies including browser extras
RUN uv pip install --system --no-cache \
    -e ./packages/core-models \
    -e ./packages/messaging \
    -e ./packages/storage \
    -e "./packages/anti-detection[browsers]" \
    -e ./apps/worker-stealth

# Install Camoufox browser binary
RUN python -m camoufox fetch || true

# =============================================================================
# Runtime
# =============================================================================
FROM python:3.13-slim

# Runtime browser dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    libgtk-3-0 \
    libdbus-glib-1-2 \
    libxt6 \
    libx11-xcb1 \
    libasound2 \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy Camoufox browser binary
COPY --from=builder /root/.camoufox /root/.camoufox

# Copy application and package source
COPY apps/worker-stealth/src/ ./src/
COPY packages/core-models/src/ ./packages/core-models/src/
COPY packages/messaging/src/ ./packages/messaging/src/
COPY packages/storage/src/ ./packages/storage/src/
COPY packages/anti-detection/src/ ./packages/anti-detection/src/

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app/src
ENV DISPLAY=:99

# Start Xvfb for headful-headless mode, then run the worker
CMD ["sh", "-c", "Xvfb :99 -screen 0 1920x1080x24 &>/dev/null & python -c 'from main import main; import asyncio; asyncio.run(main())'"]
