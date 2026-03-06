# Development commands for Arachne
# https://github.com/casey/just

# Default recipe — show available commands
default:
    @just --list

# ============================================================
# Infrastructure
# ============================================================

# Start the full local stack (infrastructure + apps)
up:
    docker compose -f infra/docker-compose.yml up -d

# Stop everything
down:
    docker compose -f infra/docker-compose.yml down

# Start infrastructure only (no app services)
infra-up:
    docker compose -f infra/docker-compose.yml up -d redpanda redpanda-console postgres postgres-temporal minio minio-init temporal temporal-ui ollama

# Start infrastructure with verbose logging
infra-up-dev:
    docker compose -f infra/docker-compose.yml -f infra/docker-compose.dev.yml up -d redpanda redpanda-console postgres postgres-temporal minio minio-init temporal temporal-ui ollama

# View infrastructure logs
infra-logs:
    docker compose -f infra/docker-compose.yml logs -f

# View logs for a specific service
infra-logs-service service:
    docker compose -f infra/docker-compose.yml logs -f {{ service }}

# Check health of all services
infra-health:
    @docker compose -f infra/docker-compose.yml ps --format "table {{{{.Name}}}}\t{{{{.Status}}}}"

# Reset everything (destroys all data)
infra-reset:
    docker compose -f infra/docker-compose.yml down -v

# ============================================================
# Development
# ============================================================

# Format all Python code
fmt:
    ruff format .

# Lint all Python code
lint:
    ruff check .

# Run all tests
test:
    pytest apps/api-gateway/tests/ apps/worker-http/tests/ packages/extraction/tests/ -v

# Run extraction package tests only
test-extraction:
    pytest packages/extraction/tests/ -v

# ============================================================
# Ollama (Local Models)
# ============================================================

# Pull recommended models for extraction
ollama-pull:
    docker exec arachne-ollama ollama pull qwen3:8b
    docker exec arachne-ollama ollama pull gemma3:27b

# Pull vision model for CAPTCHA solving (requires GPU with ≥12GB VRAM)
ollama-pull-vision:
    docker exec arachne-ollama ollama pull qwen3-vl:32b

# List loaded Ollama models
ollama-models:
    docker exec arachne-ollama ollama list

# ============================================================
# Utilities
# ============================================================

# Show service URLs after startup
urls:
    @echo "API Docs:       http://localhost:8000/docs"
    @echo "Temporal UI:    http://localhost:8088"
    @echo "Redpanda:       http://localhost:8080"
    @echo "MinIO Console:  http://localhost:9001  (user: arachne / pass: arachne123)"
    @echo "Ollama:         http://localhost:11434"
    @echo "PG Arachne:     localhost:5432  (user: arachne / pass: arachne)"
    @echo "PG Temporal:    localhost:5433  (user: temporal / pass: temporal)"
