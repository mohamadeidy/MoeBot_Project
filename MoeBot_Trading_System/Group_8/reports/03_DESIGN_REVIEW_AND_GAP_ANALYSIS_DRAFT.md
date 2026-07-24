# Group 8 Design Review and Gap Analysis — Draft

## Verdict

**DESIGN CANDIDATE: CONDITIONAL PASS / NOT FROZEN**

The proposed Group 8 scope is internally coherent and respects the frozen boundaries of Groups 1–7. It is not authorized for engine build until the dependency freeze reference and exact upstream schema gates pass.

## Review findings

### Scope separation — PASS

- Group 8 is a descriptive research and interpretation layer.
- BUY/SELL/WAIT, entries, stops, targets, sizing, PnL, MFE, MAE, future returns and profitability calibration are prohibited.
- Group 2 regime, Group 3 structure, Group 4 zones, Group 5 liquidity, Group 6 imbalance/delivery and Group 7 block definitions remain frozen read-only inputs.
- No preferred school, global confluence score, or preferred Group 7 block definition is allowed.

### Causality contract — PASS

- Event, confirmation and availability times are separate.
- Availability is the maximum of all mandatory upstream evidence.
- Creation records are immutable; lifecycle, contradiction and invalidation are append-only.
- HTF objects cannot be exposed to LTF contexts before their own confirmation and availability.
- Right-censoring is explicit.

### Definition precision — FIXED

Initial draft gap: Wyckoff and ICT/SMC hypotheses were too narrative for deterministic implementation.

Fix:

- Added `01_DEFINITION_REGISTRY_DRAFT.json`.
- Locked independent mechanical definitions and exact evidence ordering for Classical Price Action, Dow, Wyckoff and ICT/SMC.
- Defined exact candle, breakout, failure, retest, pullback, continuation, exhaustion, spring/upthrust, SOS/SOW, LPS/LPSY, accumulation/distribution, liquidity-sweep/displacement, MSS/FVG, premium/discount and upstream lifecycle relations.
- Kept all definitions independent and non-ranked.

### Configuration precision — FIXED

Initial draft gap: ATR, proximity, precision and boundary constants were not fully centralized.

Fix:

- Added `FROZEN_CONFIG_DRAFT.json`.
- ATR is Wilder RMA, period 14, closed-bar warm-up 14.
- Canonical feature precision is eight digits.
- Doji, pin/rejection, proximity and ATR-buffer breakout thresholds are explicit.
- Constants are descriptive only and are not calibrated on future outcomes.

### Persistence and immutability — FIXED

Initial draft gap: mandatory record names existed, but exact columns, keys and immutable-write enforcement were not yet defined.

Fix:

- Added `02_SCHEMA_DRAFT.sql`.
- Added registries, pattern candidates/states, school interpretations, shared/conflicting evidence, hypotheses/lifecycle, MTF relations, evidence chains, invalidations, audits and checkpoints.
- Added deterministic hash columns, foreign keys, uniqueness constraints and indexes.
- Added database triggers that reject UPDATE and DELETE on immutable creation tables.

### Upstream adapter integrity — OPEN BLOCKER

Exact Group 6 and Group 7 consumed tables/fields are documented.

Groups 2–5 still require exact table/column extraction from the verified frozen runtime archive and final PRAGMA inspection of the real annual SQLite databases. Semantic adapters must not be converted into guessed source identifiers.

Prepared controls:

- `contracts/UPSTREAM_INPUT_CONTRACT_DRAFT.json`
- `code/group8_dependency_intake.py`
- `.github/workflows/moebot-group8-dependency-intake.yml`

Required evidence:

- verified runtime-bundle restoration;
- exact source SHA-256 match for Groups 2–6;
- static source schema inventory;
- real annual SQLite `sqlite_master`, `table_info`, `foreign_key_list`, `index_list` capture;
- reviewed adapter-map hash.

### Group 7 freeze reference — OPEN BLOCKER

Required:

- `data_release_tag = moebot-group7-v0.7.5`
- `closure_tag = moebot-group7-v0.7.5-closure`
- closure tag target equals the final recorded `closure_commit_sha`;
- repository and database SHA-256 checks pass after reference repair.

The manifest and workflow repair are committed, but GitHub ref lookup still reports that the closure tag does not exist. Dependency intake cannot be declared PASS until an actual `refs/tags/moebot-group7-v0.7.5-closure` exists and resolves to the recorded commit.

## Prohibited shortcuts

- Do not substitute a branch with the same name for the required Git tag.
- Do not treat a JSON field naming a tag as proof the tag exists.
- Do not use the legacy Group 6 database identities recorded in older registry files.
- Do not start the Group 8 engine on semantic/guessed adapters.
- Do not freeze the design or begin annual execution while either blocker remains.

## Current gate state

| Gate | State |
|---|---|
| Scope and exclusions | PASS |
| Causality and lifecycle | PASS |
| Mechanical definition registry | PASS draft |
| Frozen configuration candidate | PASS draft |
| Persistence schema candidate | PASS draft |
| Group 7 repository/database verification evidence | PASS before final tag repair |
| Actual closure tag exists and target matches | BLOCKED |
| Groups 2–6 static schema inventory | PENDING RUNNER |
| Exact annual SQLite adapter map | PENDING |
| Dependency Intake | BLOCKED |
| Design Lock freeze | NOT AUTHORIZED |
| Engine build | NOT AUTHORIZED |
| Annual execution | NOT AUTHORIZED |

## Next mandatory transition

`Actual closure tag verification + frozen runtime schema inventory + exact annual adapter map → Dependency Intake PASS → freeze Design Lock → begin Group 8 engine build.`
