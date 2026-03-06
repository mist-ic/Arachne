# arachne-extraction-engine

Temporal worker service for AI-based extraction, auto-schema discovery, and CAPTCHA solving.

## Task Queue

Listens on `extract-ai` — called from `ScrapeWorkflow` (worker-http) or the API gateway.

## Activities

| Activity | Description |
|----------|-------------|
| `extract_with_llm` | Full AI extraction pipeline: MinIO HTML → preprocess → route model → extract → store |
| `discover_page_schema` | Auto-discover extraction schema for unknown sites |
| `solve_page_captcha` | CAPTCHA solving with local→external fallback chain |

## Configuration

All settings via `ARACHNE_` environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `ARACHNE_DEFAULT_MODEL` | `gemini/gemini-2.5-flash` | LiteLLM model for extraction |
| `ARACHNE_COST_MODE` | `balanced` | `minimize` / `balanced` / `accuracy` |
| `ARACHNE_OLLAMA_BASE_URL` | `http://ollama:11434` | Ollama endpoint |
| `ARACHNE_GEMINI_API_KEY` | — | Google Gemini API key |
| `ARACHNE_MAX_COST_PER_PAGE_USD` | `0.10` | Hard cost ceiling |

## Run

```bash
# Locally
python src/main.py

# Docker
docker compose -f infra/docker-compose.yml up extraction-engine
```
