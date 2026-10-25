# MoeBot Groups 9–15 — Preparation Architecture v1

## Purpose
Prepare Groups 9–15 while Group 8 is still executing, without starting downstream real-data execution early.

Preparation may include scope locks, dependency contracts, schemas, sizing tools, resource guards, synthetic tests, shard plans, and orchestration code. Real execution remains strictly gated by predecessor closure.

## Hard sequencing
- Group 9 real execution is forbidden until Group 8 is officially closed **and Checkpoint 3 is PASS**.
- Group 10 requires Group 9 official closure.
- Group 11 requires Group 10 official closure.
- Group 12 requires Group 11 official closure.
- Group 13 requires Group 12 official closure.
- Group 14 requires Group 13 official closure plus an untouched final holdout plan.
- Group 15 requires Group 14 official robustness/edge PASS. Demo validation comes before gradual live deployment.

Preparation is allowed before these gates. Real data execution is not.

## Group scopes
### Group 9 — Setup State Intelligence
Build causal setup-state recognition: forming, ready, failed, missing/invalidated. Link context → location → liquidity → displacement → structure → POI → retracement → confirmation. No trade policy is learned here.

### Group 10 — Outcome & Counterfactual Intelligence
Measure what happened after a setup became causally available: MFE, MAE, time-to-event, path outcomes, transaction-cost-aware alternatives, and counterfactual paths. No future information may leak into setup-state construction.

### Group 11 — Visual Dataset & Audit
Create deterministic chart-linked audit recipes and representative rendered samples. Do **not** pre-render or retain screenshots for every row. Store compact render recipes/indexes and generate visuals on demand.

### Group 12 — Autonomous Discovery
Discover unforced relationships, combinations, and recurring structures from frozen upstream features/outcomes. Discovery and confirmation partitions must be distinct; OOS evidence must not tune discovered semantics.

### Group 13 — Policy Learning
Learn decision policy over frozen knowledge/outcomes. Candidate action vocabulary includes WAIT / BUY / SELL / HOLD / EXIT. This group produces policy candidates and diagnostics, not broker execution.

### Group 14 — Final Validation & Robustness
Run final untouched holdout, walk-forward, robustness, stress, Monte Carlo, cost/slippage sensitivity, and failure analysis. 2023–2024 data already used by upstream engineering cannot serve as the only final untouched holdout. Prefer additional years, symbols, and/or broker feeds where available.

### Group 15 — Live Execution & Integration
Integrate the frozen validated policy with MT5/broker execution, sizing, catastrophic safety, fill/slippage audit, monitoring, and recovery. Demo execution follows proof of edge; gradual live deployment follows demo execution validation.

## Shared physical architecture
1. **Shard-native, not monolithic.** No Group 9–15 annual pipeline may require materializing all upstream history into one giant SQLite database.
2. **Read-only upstream.** Consume Group 8 and predecessor outputs through immutable manifests, compact catalogs, deterministic IDs, and selective shard access.
3. **C: is active cache only.** Preserve a default 120 GiB free-space safety floor. C: retains active raw shard(s), compact indexes/catalogs, logs, and current working databases only.
4. **D: is preferred immutable vault.** Large verified compressed outputs should move to `D:\MoeBotVault` when available. The vault must be capacity-probed and hash-verified before use. If unavailable, fail closed rather than silently filling C:.
5. **Immediate lossless compression.** Every completed large shard is zstd-compressed; archive integrity and streamed round-trip SHA-256 must match before raw deletion.
6. **Bounded raw shards.** Soft target 1.5 GB uncompressed; hard guard 2.5 GB.
7. **Manifest-first lineage.** Every shard records parent manifest hashes, schema/config identity, deterministic partition spec, row counts, logical hashes, raw SHA, compressed SHA, and causality boundary.
8. **Streaming unions.** Global duplicate/reference/fingerprint checks use sidecars/external merge; never rebuild a monolithic annual union merely to validate it.
9. **Column-selective materialization.** Each group copies only required columns for its own semantics.
10. **No screenshot explosion.** Visual data uses render recipes + deterministic samples + on-demand rendering.

## Runtime architecture
- Every nontrivial full-year stage must pass a representative benchmark and exact cardinality inventory before authorization.
- Target: <= 24 hours projected per major annual stage on current hardware.
- Hard planning block: > 48 hours projected unless a physical optimization pass reduces it or an explicit evidence-based exception is approved.
- Deterministic parallel shards are allowed only when outputs are order-independent and resource gates pass.
- Parallel worker count is capacity-bound, not fixed. CPU, memory, active raw bytes, and disk floor are checked before scheduling another shard.
- No semantic approximation is allowed for speed. Optimizations may change physical execution only.

## Storage lifecycle
```
immutable predecessor shards
        ↓
compact shard catalog / sidecars
        ↓
select only required partitions + columns
        ↓
bounded deterministic raw shard(s)
        ↓
integrity + logical hash + reference audit
        ↓
zstd lossless archive + roundtrip SHA
        ↓
vault retention / C cache eviction
```

## Accuracy rules
- Preserve event time and availability time separately.
- Every learned or measured row must state exactly what information was available at decision time.
- No backdating, no future-state joins, no post-outcome feature mutation.
- Deterministic IDs must survive rerun/repartition.
- Repartitioning is physical only; it must not alter logical row identities or hashes.
- Failed predecessor integrity means downstream execution stops immediately.

## FREE-only policy
Groups 9–15 remain FREE-only: no paid runners, paid cloud compute, subscriptions, or paid data/services may be introduced without a new explicit user decision.

## Preparation deliverable definition
A group is **PREPARED** when:
- scope and forbidden behaviors are explicit;
- predecessor and handoff contracts exist;
- storage/resource budgets exist;
- schemas/interfaces are drafted;
- synthetic parity/causality/idempotence tests exist;
- sizing/preflight tooling exists;
- real execution remains locked until predecessor official closure.

Prepared does **not** mean executed or officially passed.
