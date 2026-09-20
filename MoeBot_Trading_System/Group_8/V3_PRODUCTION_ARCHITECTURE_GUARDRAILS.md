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
