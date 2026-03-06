# =============================================================================
# Arachne Extraction Engine — Multi-stage Dockerfile
# =============================================================================
# Temporal worker for AI-based extraction, schema discovery, CAPTCHA solving.
# Optional GPU support via NVIDIA Container Toolkit runtime flag.
#
# Build:   docker build -t arachne-extraction-engine -f apps/extraction-engine/Dockerfile .
# Run:     docker run --gpus all arachne-extraction-engine   (GPU)
# Run:     docker run arachne-extraction-engine               (CPU only)
# =============================================================================

# --- Stage 1: Builder ---
FROM python:3.13-slim AS builder

WORKDIR /build

# Install build dependencies
RUN pip install --no-cache-dir uv

# Copy package definitions first for caching
COPY packages/extraction/pyproject.toml packages/extraction/pyproject.toml
COPY packages/core-models/pyproject.toml packages/core-models/pyproject.toml
COPY packages/messaging/pyproject.toml packages/messaging/pyproject.toml
COPY packages/storage/pyproject.toml packages/storage/pyproject.toml
COPY apps/extraction-engine/pyproject.toml apps/extraction-engine/pyproject.toml

# Copy source code
COPY packages/extraction/src packages/extraction/src
COPY packages/core-models/src packages/core-models/src
COPY packages/messaging/src packages/messaging/src
COPY packages/storage/src packages/storage/src
COPY apps/extraction-engine/src apps/extraction-engine/src

# Install dependencies using uv for speed
RUN uv pip install --system --no-cache \
    ./packages/core-models \
    ./packages/messaging \
    ./packages/storage \
    "./packages/extraction[vision,captcha]" \
    ./apps/extraction-engine


# --- Stage 2: Runtime ---
FROM python:3.13-slim AS runtime

LABEL maintainer="Arachne Project"
LABEL description="AI extraction engine — LLM extraction, schema discovery, CAPTCHA solving"

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application source
COPY apps/extraction-engine/src/ .

# Install lxml system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends libxml2 libxslt1.1 && \
    rm -rf /var/lib/apt/lists/*

# Health check — verify service can import core modules
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "from activities import extract_with_llm; print('ok')" || exit 1

# Environment defaults
ENV ARACHNE_TEMPORAL_ADDRESS=temporal:7233 \
    ARACHNE_TASK_QUEUE=extract-ai \
    ARACHNE_DEFAULT_MODEL=gemini/gemini-2.5-flash \
    ARACHNE_COST_MODE=balanced \
    ARACHNE_OLLAMA_BASE_URL=http://ollama:11434 \
    ARACHNE_LOG_LEVEL=INFO

# Run the Temporal worker
CMD ["python", "main.py"]
