# ADR-008: Multi-Model Extraction Routing

## Status
Accepted

## Date
2026-03-07

## Context
LLM-based data extraction from web pages can use many different models — from free local models (Ollama + Qwen3) to expensive frontier models (Gemini 2.5 Pro, GPT-4o). Different pages have different extraction complexity: a clean product listing needs a small model, while a heavily obfuscated page with tables and nested data requires a frontier model.

The challenge is routing each extraction request to the cheapest model that can achieve sufficient accuracy — maximizing extraction quality while minimizing cost.

## Considered Options

### Option 1: Single Model (Always Frontier)
- Always use the best model (e.g., Gemini 2.5 Pro)
- Simplest implementation
- Rejected: Cost-prohibitive for bulk scraping ($1.25/M input tokens × thousands of pages)

### Option 2: Single Model (Always Local)
- Always use a free local model via Ollama
- Zero API cost
- Rejected: Insufficient accuracy for complex pages, structured output parsing failures

### Option 3: Complexity-Based Routing with Cascade (Chosen)
- Estimate page complexity using lightweight heuristics (no LLM call)
- Route to the cheapest suitable model tier
- Cascade upward on extraction failure (local → fast cloud → frontier)
- Combines cost efficiency with accuracy guarantees

## Decision
Build a multi-tier extraction routing system:

1. **ComplexityEstimator**: Lightweight classifier examining preprocessed Markdown — token count, structure score (tables/lists vs prose), repeating pattern count, DOM obfuscation signals, and historical model performance per domain. Outputs 0-1 complexity score.

2. **Three-tier model cascade**:
   - **Local** (Ollama): Qwen3:8B/32B, Gemma3:27B — free, 1-3s latency, GPU required
   - **Fast Cloud** (Gemini Flash): $0.10-0.15/M tokens, 1-2s latency, excellent accuracy
   - **Frontier** (Gemini Pro): $1.25/M tokens, 3-5s latency, best accuracy

3. **Three routing modes**:
   - `minimize`: Always start local, cascade up on failure
   - `balanced`: Use complexity estimate to select starting tier
   - `accuracy`: Always use frontier model

4. **Per-domain history**: Cache which model tier succeeded for each domain to skip failed tiers on subsequent requests.

5. **Cost ceiling**: Hard per-page cost limit prevents runaway spending during cascades.

## Consequences

### Positive
- Bulk simple pages cost $0 (local models)
- Complex pages still get frontier accuracy
- Cost ceiling prevents unexpected bills
- Domain history eliminates redundant cascade attempts
- Same interface regardless of model — instructor + Pydantic ensures consistent output

### Negative
- Complexity estimation is heuristic, not perfect
- Cascade adds latency when starting tier fails (retry + escalation)
- Local models require GPU infrastructure

### Neutral
- LiteLLM abstracts provider differences, making model addition trivial
- Pricing table needs periodic updates as model costs change
- Domain history grows unbounded (should add LRU eviction in production)
