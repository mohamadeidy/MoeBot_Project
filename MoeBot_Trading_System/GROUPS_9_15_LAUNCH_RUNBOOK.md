# MoeBot Groups 9–15 Launch Runbook — Preparation v1

This runbook begins **only after Group 8 is officially closed and Checkpoint 3 is PASS**. It does not authorize early execution.

## Zero-step: protect Group 8
Do not update the current Group 8 production worktree while its 2023/2024 continuation is running. Groups 9–15 preparation remains on `groups9-15-preparation-v1` / Draft PR #160.

## When Group 8 closes

### 1. Rebase/merge preparation only after closure evidence exists
Confirm the preparation branch is based on the exact final Group 8 closure commit. If Group 8 tooling moved after this preparation branch was created, rebase the preparation branch first and rerun CI. Do not resolve conflicts by changing frozen Group 8 semantics.

### 2. Build compact predecessor catalog
Use `groups9_15_shared/manifest_catalog.py` on the final Group 8 releases. This indexes manifest metadata only and avoids opening/copying every large SQLite shard.

### 3. Group 9 compatibility probe
Run `Group_9/code/group9_group8_adapter_probe.py` against representative decompressed Group 8 shards and the final frozen Group 8 definition registry.
- Any missing table/column/definition ID = BLOCK.
- Do not silently remap IDs.

### 4. Freeze Group 9 semantics
Review the draft component-role map against final Group 8 closure evidence. Freeze exact setup assembly/state-transition rules only after Checkpoint 3 PASS. Update:
- `01_DEFINITION_REGISTRY_DRAFT.json` → frozen registry
- `PREPARATION_PLAN.json` → FROZEN
- semantic executor + `EXECUTION_COMMAND.json` → FROZEN

No 2024/holdout observations may be used to tune semantics outside the predeclared protocol.

### 5. Inventory before full run
Generate exact candidate/root inventory from manifest/catalog metadata and selective shard scans. Do not materialize the annual upstream database.

### 6. Benchmark before full run
Run a representative sample covering heavy/light months, timeframes, and definition families. Feed measured sample count/time/output/peak bytes to `group_sizing.py`.

Planning gates:
- target major annual stage <= 24h;
- >48h = BLOCK and physical optimization required;
- C: must remain >=120 GiB free;
- raw shard hard guard 2.5 GB.

### 7. Resource gate
Run `resource_gate.py` against the actual execution drive. Large retained compressed outputs belong in `D:\MoeBotVault` after hash verification. C: is active cache only.

### 8. Preflight
Run `group_preflight.py`. Real execution starts only when it returns:
- `status=PASS`
- `real_execution_authorized=true`

### 9. Shard execution
Create deterministic shard plan with `group_shard_planner.py`. Execute via `group_executor.py`.
- checkpoints make resume idempotent;
- completed raw shards are validated, zstd-compressed and round-trip SHA verified;
- raw cache is deleted only after verified retention;
- no monolithic annual union.

### 10. Streaming union + closure
Run `group_union_validator.py`, group-specific reference/fingerprint sidecars, annual/cross-year audits, then build the immutable downstream handoff with `group_handoff.py`.

### 11. Repeat sequentially
Group N+1 may be prepared in code, but real execution starts only after Group N official closure.

## Group-specific remaining freeze work

### Group 9
Final setup assembly/state definitions from final Group 8 evidence; semantic materializer; representative sizing.

### Group 10
Freeze outcome horizons, reference-price semantics, cost/slippage model and censoring; then outcome executor.

### Group 11
Freeze renderer version, overlay/annotation specification, sampling strata and audit protocol. Full-population screenshots remain forbidden.

### Group 12
Freeze chronological discovery/confirmation partitions, purge/embargo rules, candidate discovery methods, multiple-testing/stability rules.

### Group 13
Freeze objective, action semantics, model/search family, train/validation protocol and policy selection protocol. Final holdout remains inaccessible.

### Group 14
Freeze a genuinely untouched final holdout plan, walk-forward/stress/Monte Carlo/cost protocols and official edge/robustness gates.

### Group 15
Freeze MT5/broker adapter, symbol/account constraints, risk ceilings, demo acceptance gates and gradual-live deployment policy.

## Stop conditions
Any of the following stops the next run before heavy computation:
- predecessor not officially closed;
- hash/lineage mismatch;
- missing source IDs/columns/definitions;
- causality/lookahead violation;
- sizing > hard runtime budget;
- C free-space floor violation;
- shard > hard raw-size guard;
- archive round-trip SHA mismatch;
- global duplicate/reference/fingerprint failure;
- final holdout contamination.
