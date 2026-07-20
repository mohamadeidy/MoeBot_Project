# MoeBot Autonomous Trading Intelligence

This directory is the portable source-of-truth for the staged MoeBot research architecture.

## Current scope

- Group 1 — Market Memory Collector
- Group 2 — Market Regime Intelligence
- Group 3 — Market Structure Engine
- Group 4 — Support, Resistance & Zones
- Group 5 — Liquidity Intelligence
- Group 6 — Imbalance, FVG & Delivery

## Storage policy

GitHub stores only portable artifacts:

- source code
- frozen configuration
- schemas and contracts
- tests
- verification and audit reports
- handoff files
- manifests and SHA-256 registries

The following remain outside GitHub and are referenced only by metadata and SHA-256:

- large SQLite databases
- raw tick archives
- large `.tar.zst` deliveries
- MT5 tester caches and raw data packages

No missing heavy artifact may be treated as present merely because it appears in a manifest.

## Integration rule

Every group consumes only frozen upstream artifacts. Previous groups must not be rebuilt or silently modified. Event records preserve causal availability timestamps and deterministic identities.
