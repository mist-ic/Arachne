# ADR-007: Adaptive Evasion Router

## Status
Accepted

## Date
2026-03-07

## Context
Modern anti-bot systems deploy layered protections: TLS fingerprinting, JavaScript challenges, behavioral analysis, CAPTCHA, and IP reputation. No single bypass technique works against all targets. Existing open-source scrapers either use a fixed stealth approach (always browser, or always HTTP) or require manual configuration per target.

We need a system that automatically adapts its stealth level based on the target's protection and the outcomes of previous requests.

## Considered Options

### Option 1: Manual Configuration Per Domain
- User specifies which browser/proxy/behavior to use per domain
- Simple but doesn't scale and requires expert knowledge

### Option 2: Fixed Escalation Only (Chosen: Extended)
- Start at cheapest tier, escalate up on failure
- Most open-source scrapers stop here
- We extend with **de-escalation** — the key differentiator

### Option 3: ML-Based Routing
- Train models on success/failure patterns to predict optimal tier
- Overkill for current scope, but the architecture supports adding this later

## Decision
Build an Adaptive Evasion Router that:

1. **Escalates** through stealth tiers on failure:
   - Tier 0: curl_cffi (HTTP, JA4 spoofed) — fast, cheap
   - Tier 1: Pydoll (CDP, Cloudflare specialist)
   - Tier 2: Camoufox (C++ engine mods, full stealth)

2. **De-escalates** on success via Browser→HTTP handoff:
   - Browser obtains clearance cookies → export to curl_cffi → fast HTTP
   - This is how real practitioners work (Research.md §1.6)

3. **Maintains per-domain state**: tier, vendor, cookies, escalation history, circuit breaker

4. **Integrates with vendor detection**: pre-sets starting tier based on known protection

## Consequences

### Positive
- Automatically adapts to any site's protection level
- De-escalation makes the system production-practical (10-20x faster for bulk)
- No manual configuration needed for most targets
- Circuit breaker prevents wasting resources on unreachable domains

### Negative
- Increased complexity vs. fixed-tier approach
- Per-domain state requires memory (bounded by domain count)
- Incorrect vendor detection could waste time at wrong tier

### Neutral
- Architecture supports ML-based routing as a future enhancement
- Cookie TTL estimation is heuristic (30 min default, adjustable)
