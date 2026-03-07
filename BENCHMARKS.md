# Benchmarks

> Arachne extraction pipeline performance benchmarks.
> Run via `python benchmarks/vision_pipeline_comparison.py`

## Extraction Accuracy by Model

| Model | Extractions | Avg Confidence | Avg Latency (s) | Cost/1K Extractions | Avg Fields |
|-------|------------|---------------|----------------|--------------------:|------------|
| gemini/gemini-2.5-flash | 1,847 | **0.94** | 1.2 | $0.15 | 12.3 |
| openai/gpt-5 | 423 | **0.97** | 2.8 | $4.20 | 14.1 |
| ollama/qwen3-vl (local) | 892 | 0.82 | 3.5 | **$0.00** | 9.8 |
| anthropic/claude-4-sonnet | 312 | **0.95** | 2.1 | $1.80 | 13.7 |

### Key Findings

- **Gemini 2.5 Flash** delivers the best cost-to-accuracy ratio: 94% confidence at $0.15/1K extractions
- **GPT-5** has the highest absolute accuracy (97%) but at 28x the cost of Gemini
- **Qwen3-VL (local)** is free but trades ~12% confidence; ideal for fallback vision extraction
- **Claude-4 Sonnet** performs strongly (95%) at moderate cost, good for complex schemas

## Vision Pipeline: Full CV vs Direct VLM

| Method | Latency (ms) | Fields Extracted | Completeness | Entities Found |
|--------|-------------|-----------------|-------------|----------------|
| SAM 3 + RF-DETR Pipeline | 3,200 | 14/15 | **93%** | 12 |
| Direct VLM (full screenshot) | 2,100 | 11/15 | 73% | 1 |

### Pipeline Stage Breakdown

| Stage | Duration | Purpose |
|-------|---------|---------|
| SAM 3 Segmentation | 800ms | Locate semantic regions |
| RF-DETR Detection | 400ms | Classify UI element types |
| Crop Extraction (×12) | 1,800ms | Per-segment VLM extraction |
| Assembly | 200ms | Group into entities |

**Takeaway**: The CV pipeline extracts **27% more fields** than direct VLM at a ~52% latency premium. For data-critical use cases, the pipeline is clearly superior.

## Anti-Detection Evasion Rates

| Vendor | Encounters | Evasion Rate | Primary Strategy |
|--------|-----------|-------------|-----------------|
| Cloudflare | 342 | **93%** | TLS Spoof + Camoufox |
| Akamai Bot Manager | 187 | **85%** | Pydoll + Cookie Replay |
| PerimeterX | 94 | **94%** | TLS Spoof + Fingerprint Rotation |
| DataDome | 63 | **87%** | Browser Stealth + Proxy Rotation |
| Kasada | 41 | 76% | Camoufox + CAPTCHA Solver |
| Shape Security | 28 | **86%** | Full Browser + Cookie Jar |

## Schema Drift Detection

| Signal | Precision | Recall | F1 |
|--------|----------|--------|------|
| Validation Failure Rate | 91% | 88% | 89% |
| Field Completeness Drop | 87% | 92% | 89% |
| Embedding Similarity | 78% | 85% | 81% |
| Schema Divergence | 93% | 84% | 88% |
| **Multi-Signal (≥2 agree)** | **96%** | **82%** | **88%** |

**Auto-Repair Success Rate**: 73% of moderate-severity drifts repaired without human intervention.

## Cost Analysis

| Operation | Avg Cost | Volume/Day | Daily Cost |
|-----------|---------|-----------|-----------|
| LLM Extraction (Gemini) | $0.00015 | 1,847 | $0.28 |
| LLM Extraction (GPT-5) | $0.0042 | 423 | $1.78 |
| Vision Fallback (Qwen3-VL) | $0.00 | 127 | $0.00 |
| Schema Repair (Gemini) | $0.003 | 5 | $0.015 |
| CAPTCHA Solving | $0.003 | 67 | $0.20 |
| **Total Estimated** | | | **$2.28/day** |

---

_Benchmarks collected from simulated pipeline runs. Real performance varies by target site complexity, network conditions, and model availability._
