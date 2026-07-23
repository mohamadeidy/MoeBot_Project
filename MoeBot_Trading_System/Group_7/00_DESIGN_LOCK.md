# MoeBot Group 7 — Blocks and Institutional Zones
## Mandatory Design Lock v0.7.0

**Status:** LOCKED FOR BUILD / SYNTHETIC AND TECHNICAL VALIDATION  
**Upstream:** Groups 2–6 are frozen, read-only dependencies. Group 6 v0.6.4 / schema 6.35.0 is the direct dependency.  
**Purpose:** Test multiple causal, auditable definitions of blocks and institutional zones without merging them, ranking them, trading them, or inferring profitability.

## 1. Non-negotiable scope boundary

Group 7 emits descriptive research objects only. It does not emit BUY, SELL, WAIT, entries, stops, targets, position sizing, setup scores, profitability optimization, PnL, MFE, MAE, or future-return labels. It does not modify or rediscover Group 2 regime, Group 3 structure, Group 4 zones, Group 5 liquidity, or Group 6 imbalance/displacement logic.

Group 6 neutral origin references remain neutral inputs. An origin reference becomes a Group 7 zone only if one specific locked definition passes. Passing one definition never implies that another definition passed.

## 2. Frozen direct inputs from Group 6

For every displacement leg Group 7 may consume only already-stored causal fields and evidence:

- origin bar ID;
- origin window start/end;
- body, wick, and full ranges;
- base duration;
- first impulse bar ID;
- last opposing candle reference;
- leg direction, classification, uncertainty, confirmation, and availability;
- related FVG IDs and their own availability times;
- causal BOS/MSS/CHOCH evidence IDs;
- causal liquidity-event/pool/void IDs;
- Group 6 config, dataset, source, dependency, feature, and record hashes.

The immutable canonical bar database is read only and is used only to recover the exact OHLC of referenced bar IDs and to advance lifecycle state causally.

## 3. Independent definition registry

All definitions are evaluated independently and every pass/fail evaluation is persisted with canonical feature payload, reasons, feature hash, and deterministic evaluation ID.

### D1 — Strict Order Block

A leg passes only when all are true:

1. Group 6 leg is `validated` and `uncertain=0`.
2. A last opposing candle exists and is available through the leg record.
3. At least one causally available associated classic FVG exists for that leg.
4. At least one causally available Group 3 `BOS` or `MSS` evidence item exists in the leg evidence chain.
5. The zone range is the **body range of the exact last opposing candle**.
6. Availability is the maximum of leg availability, qualifying FVG availability, and BOS/MSS evidence availability.

### D2 — Loose Order Block

A leg passes when it is a Group 6 displacement candidate or validated leg and has a non-zero neutral origin full range. No BOS/MSS or FVG is required. The zone is the full neutral origin-window range. Availability equals leg availability.

### D3 — Last Opposing Candle

A leg passes when an exact last opposing candle exists and its candle direction is opposite the displacement direction. The zone is the full high–low range of that candle. Availability equals leg availability. No FVG or structural break is required.

### D4 — Breaker Block

A breaker is never created retrospectively at parent creation. It is derived only after:

1. a D1, D2, or D3 parent zone becomes causally invalidated by its locked close-through rule; and
2. a later, already-confirmed opposite-direction Group 3 BOS or MSS evidence item becomes available.

The breaker direction is opposite the parent direction, the range is inherited from the parent, and availability is the later BOS/MSS availability. The parent remains immutable and the parent relation is stored explicitly. When the same source leg produces multiple eligible parent definitions, the frozen non-future priority is `Strict Order Block → Last Opposing Candle → Loose Order Block`; lower-priority parents retain their own lifecycle but do not create duplicate breakers.

### D5 — Mitigation Block

A mitigation block is derived only after a D1, D2, or D3 parent receives its first causal visit without prior invalidation, and a later same-direction validated Group 6 displacement leg departs from an overlapping range. Availability is the later leg availability. The range is the intersection of parent range and the later leg neutral origin full range. The parent visit and confirming leg are explicit evidence.

### D6 — Rejection Block

A leg passes when its exact last opposing candle has a dominant rejection wick in the future displacement direction:

- bullish leg: lower wick / full range >= 0.50 and close location in upper half;
- bearish leg: upper wick / full range >= 0.50 and close location in lower half.

The zone is the rejecting wick segment only. Availability equals leg availability. This is a mechanical candle-shape definition, not proof of intent.

### D7 — Propulsion Block

A leg passes when:

1. it is validated and not uncertain;
2. the first impulse candle is directionally aligned with the leg;
3. a causally available associated FVG exists; and
4. a causally available BOS or MSS exists.

The zone is the first impulse candle body range. Availability is the maximum of leg, FVG, and BOS/MSS availability. This definition is independent of D1 even when both pass.

### D8 — Supply/Demand Origin

A leg passes when it is validated, the neutral base duration is at least two bars, and the neutral origin full range is non-zero. Bullish legs produce demand-origin labels; bearish legs produce supply-origin labels. The zone is the neutral origin full range and availability equals leg availability.

## 4. Lifecycle and freshness

Creation records are immutable. Lifecycle changes are append-only state transitions.

Initial state: `fresh_valid` with zero visits and zero mitigations.

A bar is eligible to interact only when its close time is **strictly greater** than zone availability.

- Edge equality counts as a touch.
- A distinct visit begins when a bar overlaps the range after at least one non-overlapping bar.
- First visit emits `first_touch` and changes freshness to `tested_valid`.
- Each completed or right-censored visit is stored separately.
- A visit with penetration greater than zero increments mitigation count once; multiple bars inside the same visit do not create multiple mitigations.
- Maximum penetration is monotonic and stored in transitions and summary.
- No arbitrary age expiry is allowed in Group 7.

## 5. Invalidation rules

Wick breaches alone never invalidate.

- D1 Strict OB, D3 Last Opposing Candle, D6 Rejection Block, D7 Propulsion Block, D4 Breaker, and D5 Mitigation Block: one closed candle strictly beyond the far boundary invalidates.
- D2 Loose OB and D8 Supply/Demand Origin: two consecutive closed candles strictly beyond the far boundary invalidate.
- Bullish zone far boundary = lower bound; bearish zone far boundary = upper bound.
- Exact equality is not close-through.
- Invalidation-candidate and final invalidation are separate transitions for two-close definitions.

## 6. Evidence and relationships

Evidence is append-only and time-stamped. Stored relations include:

- source displacement leg;
- origin bar/window and exact referenced candles;
- associated FVG and overlap geometry;
- BOS/MSS/CHOCH relation without redefining structure;
- liquidity event/pool/void relation without redefining liquidity;
- Group 4 zone overlap when present in Group 6 evidence;
- parent/derived relations for breaker and mitigation blocks;
- overlap relations between independently created Group 7 definitions.

No confluence score, voting, preferred block, or setup object is permitted.

## 7. Causality, determinism, and persistence

- Closed bars only.
- Store event time, confirmation time, and availability time separately.
- No object or evidence may be available before all mandatory source evidence is available.
- No later lifecycle state may rewrite a creation record.
- Deterministic IDs include frozen source identities and canonical creation payloads, not future lifecycle outcomes.
- Canonical JSON is persisted for every definition evaluation and feature-bearing record.
- Every record stores a reconstruction hash.
- Batch, streaming, checkpoint/restart, prefix/future-append, and full rebuild paths must agree.
- Exact duplicate import adds zero records; conflicting duplicate identity raises an explicit error.
- Config hash, source fingerprint, Group 6 dependency hash, and transitive Groups 2–5 dependency hashes are stored.

## 8. Mandatory output tables

At minimum:

- `config_registry`, `dataset_registry`, `dependency_registry`, `definition_registry`;
- `block_evaluations`;
- `institutional_zones`;
- `zone_evidence`;
- `zone_relations`;
- `zone_state_transitions`;
- `zone_visit_observations`;
- `zone_lifecycle_summary`;
- `group7_audit_evidence`;
- `processing_checkpoints`.

## 9. Mandatory validation loop

Design Lock → Build → Synthetic Tests → 2023 Build/Review → Gap Analysis → Fix → Retest → Independent Audit → frozen 2024 out-of-sample validation → cross-year validation → visual audit → final verification.

A technical candidate may pass before annual databases are present, but the verdict `Group 7 officially closed` is forbidden until both frozen annual Group 6 databases and their immutable source-bar databases have been built, independently audited, visually reviewed, and passed cross-year validation without changing this lock.

## v0.7.5 causal implementation clarification

This clarification does not change any Order Block definition or threshold. Every Group 6 displacement leg creates six immutable base-definition candidates using only information available with the leg. A candidate becomes a definition match only when that definition's exact required evidence is available. Match availability is the maximum of candidate availability and the selected validation/FVG/BOS-MSS evidence availability times. Institutional-zone availability equals the match availability and lifecycle processing cannot begin earlier. Candidate, match, and lifecycle records remain separate. Later evidence may append a later relationship but may never rewrite an earlier candidate or backdate a match or zone.
