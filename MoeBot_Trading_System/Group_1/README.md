# Group 1 — Data Integrity & Market Memory

This directory preserves the frozen Group 1 dependencies required by later MoeBot groups.

## Canonical runtime identity

- Collector: `MoeBot_Group1_MarketMemory_Collector_v0.9.2.mq5`
- Collector version: `0.9.2`
- Spool schema: `1.4.0`
- Required SHA-256: `5bad54ebdeadba2cdbb4cb63f8d411a4ccba68ae47f9dbe714627d48bf231bb7`
- Scope: causal market-data acquisition only; no trading decisions or order operations.

## Directory layout

- `code/` — exact frozen MQL5 collector source.
- `design/` — Group 1 Design Lock and architectural constraints.
- `reports/` — local deterministic verification evidence and remaining native gates.
- `registry/` — version lock, checksums, and provenance notes.

## Heavy data policy

Raw Collector archives and generated SQLite databases are intentionally not committed here. They are reproducible runtime outputs and may be recreated when required. Later groups must validate any recreated database against the frozen source/config identities and recorded hashes before use.

## Dependency rule

Later groups may consume Group 1 data products as frozen read-only inputs. They must not modify Group 1 collection semantics, manufacture missing bars, or substitute a different collector version while claiming compatibility with the official v0.9.2 source.
