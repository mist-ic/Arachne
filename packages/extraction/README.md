# arachne-extraction

AI-first extraction engine for structured data extraction from web pages.

## Components

| Module | Description |
|--------|-------------|
| `preprocessor` | HTML→Markdown pipeline with DOM pruning, link-to-citation conversion, content scoring |
| `chunker` | Context-aware markdown chunking with table preservation and sentence overlap |
| `llm_extractor` | instructor + LiteLLM schema-bound extraction with conditional reattempt |
| `model_router` | Multi-model routing with complexity estimation, cost/SLO constraints, cascade fallback |
| `schema_discovery` | Auto-schema discovery via pure LLM or hybrid DOM+LLM (repeated subtree detection) |
| `captcha/` | CAPTCHA detection, local vision solving (Qwen3-VL), external API solving (2Captcha, CapSolver) |

## Quick Start

```python
from arachne_extraction import preprocess, ExtractionRouter
from pydantic import BaseModel

class Product(BaseModel):
    name: str
    price: float
    description: str | None = None

# Preprocess raw HTML
result = preprocess(raw_html)

# Route to optimal model and extract
router = ExtractionRouter(api_keys={"GEMINI_API_KEY": "..."})
output = await router.extract(result.markdown, Product, url="https://shop.example.com")
print(output.data)  # Product(name='Widget', price=29.99, ...)
```

## Architecture

```
Raw HTML → prune_dom → html_to_markdown → chunk_markdown
                                              ↓
                                    ComplexityEstimator
                                              ↓
                                    ExtractionRouter
                                    ↓         ↓        ↓
                                Local    Fast Cloud  Frontier
                               (Ollama)  (Flash)     (Pro)
                                              ↓
                                    ExtractionOutput
                                    (data, cost, confidence)
```

## Tests

```bash
uv run pytest tests/ -v
```
