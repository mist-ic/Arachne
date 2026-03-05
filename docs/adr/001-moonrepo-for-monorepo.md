# ADR-001: Moonrepo for Monorepo Management

## Status
Accepted

## Context

Arachne is a polyglot project — Python for the backend pipeline (API, workers, extraction, ML models) and TypeScript for the dashboard UI. We needed a monorepo tool that:

1. Treats both Python and TypeScript as first-class citizens
2. Provides deterministic caching and cross-language task graphs
3. Signals cutting-edge tooling awareness (portfolio signal)
4. Works well in a Docker Compose-based local development setup

### Alternatives Considered

| Tool | Verdict | Why |
|---|---|---|
| **Turborepo** | ❌ Rejected | JS/TS only — zero Python support |
| **Nx** | ❌ Rejected | JS-first, Python support via community plugins and workarounds |
| **Pants** | ❌ Rejected | Powerful but extreme learning curve; overkill for portfolio scope |
| **Bazel** | ❌ Rejected | Google-scale tool; massive overhead for a portfolio project |
| **No tool** | ❌ Rejected | Loses the "this engineer thinks at scale" signal |

## Decision

Use **Moonrepo** as the monorepo management tool.

Key factors:
- Two of three independent research agents recommended it
- Native polyglot support (Python + TypeScript as first-class citizens)
- Rust-based CLI — fast, single binary
- Deterministic caching reduces rebuild times
- Task dependency graphs across language boundaries
- Growing ecosystem with active development

## Consequences

### Positive
- Clean project discovery via `apps/*` and `packages/*` globs
- Cross-language task orchestration (e.g., "build dashboard" depends on "generate API types")
- Deterministic caching speeds up CI
- Strong portfolio signal — demonstrates awareness of modern build tooling

### Negative
- Smaller community compared to Nx (less Stack Overflow answers)
- Python toolchain support is still WIP in v2 (works but less mature than Node.js)
- Team members may need ramp-up time on Moon-specific concepts

### Mitigations
- Python dependency management handed off to `uv` (which Moon integrates with)
- Comprehensive Justfile provides fallback CLI commands that don't require Moon knowledge
