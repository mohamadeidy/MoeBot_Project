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
