# MoeBot Trading System — Staged Intelligence

Canonical portable workspace for the staged MoeBot Autonomous Trading Intelligence project.

## Included now

- Group 1 — Market Memory Collector
- Group 2 — Market Regime Intelligence
- Group 3 — Market Structure Engine
- Group 4 — Support, Resistance & Zones
- Group 5 — Liquidity Intelligence
- Group 6 — Imbalance, FVG & Delivery

Group 7 is intentionally excluded until its formal closure.

## Storage policy

Normal Git stores only portable source, frozen configuration, schemas/contracts, validators, tests, manifests, checksums, and final handoff records.

Large SQLite databases, raw ticks, and multi-gigabyte archives remain outside Git and are tracked by exact filename, byte size where known, and SHA-256.

No Git LFS, GitHub Actions, Codespaces, paid storage, or automatic billing change may be enabled without the owner's explicit approval first.
