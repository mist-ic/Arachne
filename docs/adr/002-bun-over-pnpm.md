# ADR-002: Bun over pnpm for JavaScript/TypeScript Toolchain

**Status**: Accepted
**Date**: 2026-03-05

## Context

Arachne is a Python-primary monorepo managed by Moonrepo. The only TypeScript component is a single React+Vite dashboard app (Phase 4). We need a JavaScript package manager and runtime for this app.

The initial plan defaulted to Node.js 22 + pnpm 9.15 as the mature, safe choice. This decision was revisited after evaluating Bun's current status (v1.3.10, March 2026).

## Decision

Use **Bun 1.3.10** as the JavaScript runtime and package manager, replacing Node.js + pnpm.

## Reasoning

1. **Single TS app = minimal risk**: With only one React+Vite dashboard, we won't hit the complex cross-workspace edge cases where pnpm's stricter hoisting control shines.

2. **Speed**: Bun installs are ~28x faster than npm (vs pnpm's ~4.7x). This matters in CI.

3. **All-in-one**: Bun is runtime + package manager + bundler + test runner. Eliminates the Node.js + pnpm + npx stack.

4. **Moonrepo first-class support**: Official since moon v1.17 (Nov 2023). Dedicated Bun handbook in docs. WASM-powered toolchain in v1.40+. Auto-downloads via proto, parses `bun.lock` for task hashing.

5. **Portfolio signal**: Consistent with Arachne's philosophy of choosing cutting-edge tools over incumbents (Redpanda over Kafka, Moonrepo over Nx, ClickStack over Prometheus+Grafana).

6. **Stability**: Anthropic acquired Bun in Dec 2025. Bun powers Claude Code ($1B ARR), giving Anthropic strong incentive to maintain stability. Version 1.3.10 addresses early 1.3.x bugs.

7. **Text lockfile**: `bun.lock` (since v1.2) is human-readable and diff-friendly, same as `pnpm-lock.yaml`.

## Alternatives Considered

| Alternative | Why Rejected |
|---|---|
| **pnpm** | Battle-tested but safe/boring. Overkill monorepo features for a single TS app. Doesn't signal cutting-edge awareness. |
| **npm** | Slowest, least strict, no unique advantages |
| **yarn** | Berry (v4) has complexity overhead, declining mindshare |

## Consequences

- Pin Bun version explicitly (`1.3.10`) to avoid surprise breakage from isolated install changes
- Use `bunx create-vite` (not `bun create vite`) for Vite scaffolding
- `bun.lock` is committed (not ignored)
- Run Vite dev server with `bun run dev`
- If Bun causes issues with specific npm packages, can fall back to Node.js + pnpm with zero application code changes (only `toolchain.yml` config)
