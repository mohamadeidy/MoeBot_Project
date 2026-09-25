# Group 8 V3 Production Architecture Guardrails

Status: **MANDATORY / NON-SEMANTIC ARCHITECTURE CHANGE ONLY**

## Primary preservation rule

Group 8 V3 MUST preserve all valid completed work from Groups 1-7 and all already-PASS Group 8 boundaries.

The V3 work is an execution/storage architecture change, not a trading-semantics redesign.

## Non-negotiable invariants

1. **Groups 1-7 remain read-only upstream dependencies.**
   - No mutation of their databases, manifests, IDs, hashes, contracts, or lineage.
   - No re-running prior PASS stages unless an independently proven integrity defect requires it and the change is explicitly approved.

2. **Existing Group 8 semantics remain frozen.**
   - Definitions, thresholds, event semantics, causal ordering, and evidence meaning do not change.
   - Immutable IDs and row hashes must match the frozen reference engine for logically equivalent rows.
   - Existing evidence contracts remain valid.

3. **Stage 5 is a protected recovery boundary.**
   - V3 execution must be able to start from the verified Stage 5 boundary without replaying earlier PASS stages.
   - Recovery procedures must never manually delete or move a live SQLite journal or database while a transaction/recovery is active.

4. **V3 may change only physical execution/storage behavior.**
   Allowed changes include:
   - deterministic batching/chunking;
   - bounded transactions and commit-per-chunk;
   - checkpoint/resume;
   - idempotent execution;
   - storage-budget preflight gates;
   - representative benchmarks and projections;
   - query/index optimization proven by parity;
   - physical sharding under the already-frozen lossless sharded storage contract;
   - downstream compatibility views/adapters/catalogs.

5. **No semantic compression.**
   - Rows may not be removed, merged, deduplicated, summarized, or replaced merely to reduce storage if doing so changes the frozen logical dataset.
   - If high cardinality is inherent in the frozen evidence model, V3 must preserve it and solve the problem physically through chunking/sharding/indexing.
   - Any proposal for logical/materialization reduction requires separate parity proof and explicit approval before adoption.

6. **Downstream Groups 9-15 compatibility is a release gate.**
   - Group 8 V3 outputs must remain consumable through the frozen logical schema/contracts expected by later groups.
   - Physical shard placement must be transparent to downstream logic through a verified compatibility/catalog layer.
   - Later groups must not need rewritten trading semantics because of V3 storage choices.

7. **GitHub is the code authority.**
   - V3 code, tests, benchmarks, compatibility checks, manifests, and receipts must exist on a dedicated GitHub branch before server deployment.
   - Server deployment must reference a known commit SHA.
   - Large runtime databases remain on server/storage; GitHub stores code and compact evidence only.

8. **Parity is required before annual execution.**
   V3 must demonstrate:
   - domain-row ID/hash parity against the frozen reference implementation on representative fixtures;
   - no unexpected definitions;
   - checkpoint idempotence;
   - crash/resume equivalence;
   - shard-union equivalence;
   - downstream logical-contract compatibility.

9. **Stage 7 remains blocked until Stage 6 V3 is proven.**
   - Stage 7 ICT must receive its own profiling, N+1 review, representative benchmark, storage projection, and parity proof before annual execution.

## V3 release gate

A V3 implementation is not eligible for server annual execution unless all of the following are PASS:

- upstream Groups 1-7 preservation audit;
- frozen Group 8 semantics audit;
- representative output parity;
- crash/resume parity;
- idempotent rerun parity;
- storage projection within configured budget;
- runtime projection within configured budget;
- shard/compatibility-layer union validation;
- downstream contract compatibility;
- known GitHub commit receipt.

Any failure is fail-closed and MUST NOT auto-launch Stage 7.


## Recovered physical Stage-5 source with legacy Stage-6 rows

A crash/rollback recovery may leave previously committed legacy Stage-6 domain rows in the same SQLite file while the authoritative `wyckoff_core` PASS checkpoint is absent. V3 preserves that file byte-for-byte and treats it as a **logical Stage-5 boundary**:

- Stage-5 PASS coverage remains authoritative and must match all expected symbol/timeframe pairs.
- A Stage-6 PASS checkpoint remains forbidden.
- V3 reads only frozen Stage-5 inputs required by Stage 6 (bounded ranges and DOW context).
- Pre-existing Stage-6 rows are audit-only contamination: they are counted in preflight, never read as V3 input, never merged into V3 output, and never deleted.
- Official Stage-6 output is solely the validated range_chain shard union produced by V3.


## Frozen-definition conformance correction: latest Dow state per layer

The 2023 Stage-6 preflight exposed a historical fan-out implementation defect: the legacy Wyckoff range loop joined each bounded range to every prior `dow_indeterminate_structure` row. That behavior conflicts with the already-frozen definition registry:

- `dow_indeterminate_structure` mandatory input: `causally_latest_group3_structure_state_per_layer`;
- `wyckoff_range_context` mandatory input: same-timeframe/layer Dow indeterminate structure;
- WYC1.1 pass rule requires causal overlap in symbol, timeframe, layer and time scope.

V3 therefore selects exactly the latest causally available indeterminate Dow state for the bounded range's exact layer. This is an implementation conformance correction, not a definition/threshold/ID/hash change. Any retained logical row continues to use the frozen writer and therefore preserves its deterministic ID/hash. Historical Dow rows remain immutable evidence; they are simply not all re-used as simultaneous current context for a later range.


## Union validation of recovered physical Stage-6 contamination

The official V3 Stage-6 union explicitly excludes any legacy Stage-6 rows that remain physically present in the recovered Stage-5 SQLite source. Union validation records their count for audit, requires that no Stage-6 PASS checkpoint exists in the logical Stage-5 boundary, and never mutates the source database.

When a new V3 shard deterministically reproduces an interpretation ID that also exists in the legacy physical rows, the row hash must be identical. A same-ID/different-hash collision is a hard validation failure. This preserves deterministic-ID integrity while preventing recovered legacy material from entering the official V3 shard union.
