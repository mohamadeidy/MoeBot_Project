# MoeBot Groups 1–6 Integration Rules

1. GitHub is the portable source-and-document registry, not the storage location for multi-gigabyte research databases or raw ticks.
2. Every group consumes only the frozen upstream version recorded in the artifact registry.
3. A manifest entry does not prove the corresponding binary is available.
4. Never replace a missing official artifact with an older or rebuilt package without explicit approval and a new validation cycle.
5. Preserve deterministic IDs, source fingerprints, config IDs, schema versions, `event_time`, confirmation time, and `availability_time` across handoffs.
6. Store heavy artifacts locally as read-only files and verify exact filename, byte size, and SHA-256 before execution.
7. No Git LFS, GitHub Actions, Codespaces, paid storage, or other chargeable GitHub feature may be enabled without explicit owner approval.
8. Groups 1–6 are research/intelligence layers; no downstream module may silently add trading decisions to their frozen outputs.
