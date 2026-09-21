# Group 8 V3 Stage 7 ICT Preflight and Gap Plan

Status: **READ-ONLY PROFILING ONLY / ANNUAL STAGE 7 REMAINS BLOCKED**

Stage 6 is an official PASS prerequisite. Stage 7 must not reuse the legacy monolithic execution path without a new cardinality, runtime, storage, parity, and resume proof.

## Frozen semantic findings

The six ICT/SMC definitions remain frozen. No thresholds, definitions, IDs, hashes, availability semantics, or upstream identities are changed.

The current `process_ict` implementation contains several non-semantic N+1 patterns that are eligible for optimization:

- Group 5 liquidity-event lookup per Group 6 evidence row;
- Group 3 break-event lookup per FVG;
- bounded-range invalidator queries per range;
- Group 7 zone-evidence lookup per zone;
- latest Group 3 structure-state lookup per draw state.

The dominant cardinality risk is `ict_premium_discount_context`, whose frozen enumeration rule is one interpretation per exact `(bounded_range_context_id, bar_id)` while the locked range remains valid.

## Return-to-imbalance evidence coverage

The frozen Group 8 adapter exposes:

- `fvg_state_transitions` for causal FVG/CE lifecycle observations;
- `inversion_fvg_relations` including `first_retest_time`;
- BPR and liquidity-void objects, but not their state-transition tables.

Therefore V3 must never infer a later BPR/void touch or visit from aggregate end-state fields without an exact causal event time. Missing upstream lifecycle evidence is preserved as unavailable evidence, not rediscovered from raw price.

The current engine does not emit inversion-retest return-to-imbalance rows. The V3 preflight measures those rows separately and marks them for semantic-conformance review before any executor change.

## Release gate

The Stage 7 preflight is diagnostic only. It can never authorize an annual Stage 7 run. Annual execution remains blocked until all of these are PASS:

1. exact cardinality inventory;
2. frozen-definition conformance review;
3. optimized Stage 7 executor;
4. representative parity benchmark against the frozen reference behavior for retained semantics;
5. crash/resume and idempotence proof;
6. storage/runtime projections within configured budget;
7. Stage 7 shard-union validation;
8. downstream Groups 9-15 compatibility proof.

2024 OOS remains forbidden.


## Representative premium/discount benchmark

Because ICT3.1 premium/discount rows dominate the 2023 Stage-7 cardinality, the V3 production path requires a representative measured benchmark before any annual execution. The benchmark:

- samples bounded-range roots deterministically across all timeframe/month windows;
- uses the frozen Group8 interpretation/evidence writers unchanged;
- preserves exact deterministic IDs, hashes, availability, reasons, evidence-strength payloads and evidence-chain rows;
- commits in bounded chunks;
- measures variable SQLite bytes and runtime per interpretation;
- projects preliminary range-chain bucket counts against the frozen 1.5 GB soft / 2.5 GB hard shard guards;
- remains diagnostic only and cannot authorize annual Stage 7.

A synthetic parity test compares the benchmark's complete premium/discount row set with the frozen reference \`process_ict\` implementation for the same fixture.

The representative benchmark is itself a CI release gate; server execution is forbidden until its compile, frozen-regression, parity, and fail-closed checks pass on the exact branch head.


## Stage 7 V3 production shard executor

The V3 executor preserves the frozen Stage-7 logical row set and splits physical execution into two contract-defined families:

- \`range_chain\`: \`ict_premium_discount_context\`, rooted at the immutable \`pa_bounded_range_context.candidate_id\`;
- \`school_core\`: ICT1.1/ICT2.1/ICT4.1/ICT5.1/ICT6.1, rooted at the first mandatory immutable upstream evidence identity, qualified by source group/type/id before bucket hashing.

The optimized school-core path removes reference N+1 queries through immutable maps, SQL joins, and a sorted/bisected latest-structure lookup. It does not change definition logic.

Every production shard:
1. reads Stage 5 and Groups 1-7 read-only;
2. writes deterministic frozen IDs/hashes through the frozen Group8 writer;
3. commits in bounded chunks with an external checkpoint;
4. validates SQLite quick/integrity/foreign-key checks and logical fingerprints;
5. may be compressed only after raw SHA verification;
6. requires \`zstd -t\` plus streamed decompression SHA equality before deleting the raw SQLite shard.

The annual orchestrator remains blocked until executor parity, resume/idempotence, measured school-core sizing, compression-gate evidence, and a frozen Stage-7 plan pass.


## Compression and school-core measurement gates

The manually demonstrated zstd round trip is formalized by \`group8_v3_stage7_compression_gate.py\`. The gate recompresses the measured premium/discount benchmark sample, verifies \`zstd -t\`, hashes streamed decompression, and compares projected compressed annual storage plus one maximum raw shard against the configured free-space safety floor.

The remaining five ICT definitions are measured independently by \`group8_v3_stage7_school_core_benchmark.py\`, which executes only a deterministic representative set of timeframe/month windows through the production shard executor, validates each shard, compresses it losslessly, deletes raw samples only after round-trip verification, and projects school-core runtime/storage. Neither measurement authorizes annual Stage 7.


## Exact annual shard-plan freeze

Annual Stage 7 may not launch from window averages. \`group8_v3_stage7_plan.py\` recomputes exact premium/discount cardinality per bounded-range root and exact school-core cardinality per first mandatory evidence root, then applies the frozen hash-bucket rule. Bucket counts are increased only in powers of two until every guarded raw-shard projection is below the 1.5 GB soft target; the 2.5 GB hard guard remains absolute.

The plan also reconciles exact interpretation totals against the Stage-7 preflight, binds Stage-5/Stage-6/report hashes and the exact Git commit, and verifies projected compressed annual peak storage against the 120 GiB safety floor. A PASS plan still cannot auto-launch Stage 7; explicit user launch remains required.


## Annual plan freeze gate

\`group8_v3_stage7_annual_plan.py\` is the non-executing release gate that binds all Stage-7 measurement evidence to the exact Git commit and Stage-5/Stage-6 lineage. It recomputes exact school-core interpretation cardinality per timeframe/root month from read-only upstream tables, verifies that the sum equals the frozen preflight cardinality, selects power-of-two bucket counts from measured bytes-per-row under the frozen 1.5 GB soft target, enforces the 2.5 GB hard guard, and checks projected compressed storage plus one raw shard against the configured safety floor.

A PASS plan permits construction/testing of the annual orchestrator; it does not itself authorize or auto-launch Stage 7.
