# MoeBot Group 8 — Price Action & Trading Schools Intelligence
## Design Lock Draft v0.8.0-draft.1

**Status:** DRAFT ONLY — NOT FROZEN — ENGINE BUILD AND ANNUAL EXECUTION FORBIDDEN UNTIL DEPENDENCY INTAKE PASS  
**Direct dependency:** Group 7 v0.7.5 / schema 7.5.0, frozen read-only.  
**Transitive dependencies:** Groups 1–6, frozen read-only.  
**Accepted annual lineage:** `dukascopy_rebuild_v1`.  
**Data release tag:** `moebot-group7-v0.7.5`.  
**Required closure tag:** `moebot-group7-v0.7.5-closure`.

## 1. Purpose

Group 8 converts established price-action concepts and trading-school interpretations into a numerical, causal, auditable, testable, and reproducible research layer.

It describes what evidence was available, how multiple schools could interpret that evidence, where interpretations overlap or conflict, how hypotheses evolve causally, and what evidence invalidates them.

It is not a trading strategy, signal generator, entry engine, optimizer, or profitability model.

## 2. Non-negotiable scope boundary

Group 8 must never emit or infer:

- BUY, SELL, WAIT, EXIT, long, short, entry, trigger, stop loss, take profit, position size, risk, leverage, trade frequency, setup grade, preferred setup, or execution instruction;
- PnL, MFE, MAE, future return, hit rate, expectancy, Sharpe ratio, profit factor, profitability labels, or any calibration against later price outcomes;
- a preferred school, preferred narrative, preferred Order Block definition, global confluence vote, trading score, or ranking intended to select a trade;
- retroactive availability, look-ahead labels, future-confirmed backdating, repainting, or mutation of an immutable creation record;
- redefinition or rediscovery of Group 1 bars, Group 2 regime, Group 3 structure, Group 4 zones, Group 5 liquidity, Group 6 imbalance/delivery, or Group 7 block definitions and lifecycle.

Group 8 consumes upstream IDs and facts read-only. It creates only Group 8 pattern, interpretation, evidence-relation, hypothesis, lifecycle, and invalidation records.

## 3. Dependency and freeze gate

No engine source, frozen config, synthetic suite, annual build, or annual output may be declared official until all are true:

1. `data_release_tag == moebot-group7-v0.7.5` remains unchanged and continues to identify only the published annual database assets.
2. `closure_tag == moebot-group7-v0.7.5-closure` exists as a Git tag.
3. The closure tag resolves exactly to the `closure_commit_sha` recorded in Group 7 `NEXT_GROUP_DEPENDENCY_MANIFEST.json`.
4. All Group 7 repository-file sizes and SHA-256 values pass.
5. Both Group 7 annual database filenames, byte sizes, compressed and extracted SHA-256 identities pass.
6. SQLite `quick_check`, `integrity_check`, and foreign-key checks pass for both years.
7. The exact Groups 2–6 frozen runtime archive restores with SHA-256 `174f776cd8d0e8a56b253a98a18027a61351834cc490dd1bfb6b0eb8d63c56cf`.
8. Exact consumed table/column adapters are generated from real read-only SQLite schemas; guessed identifiers are forbidden.
9. Legacy Group 6 artifact identities are rejected. Only the `dukascopy_rebuild_v1` identities inherited through the final Group 7 registry are accepted.

## 4. Time and causality contract

Every Group 8 object stores separately:

- `event_time`: when the described market event occurred;
- `confirmation_time`: when the locked definition became confirmable on closed data;
- `availability_time`: the maximum availability of every mandatory source record and source bar.

Rules:

- Closed bars only.
- A Group 8 object cannot be available before all mandatory upstream evidence is available.
- Later evidence may append relations, lifecycle transitions, contradiction, or invalidation records; it may not rewrite or backdate creation.
- An HTF interpretation cannot be visible to an LTF before the HTF source close and upstream availability.
- Equality and floating-point behavior use a locked symbol-aware epsilon derived from verified point/tick-size metadata where available; otherwise use exact stored-price equality and record the limitation.
- Right-censored objects remain explicitly right-censored. No future completion may be fabricated.

## 5. Numerical feature layer

All pattern and interpretation records may use only causal features available at record availability.

### 5.1 Candle anatomy

For each closed bar:

- full range;
- body size;
- upper and lower wick sizes;
- body-to-range ratio;
- upper-wick-to-range and lower-wick-to-range ratios;
- close location in range;
- open location in range;
- direction;
- range / verified ATR;
- body / verified ATR;
- wick / verified ATR;
- gap from prior close where applicable;
- overlap with prior bar;
- normalized distance to causally available Group 3/4/5/6/7 objects.

ATR and any rolling statistic must be computed from closed bars ending no later than the candidate availability time. The exact window and warm-up policy are frozen in configuration and stored with every feature hash.

### 5.2 Scale and precision

- Store raw price geometry and normalized features separately.
- Round only canonical feature payloads using the frozen precision; never round source prices before geometry tests.
- Tests must prove invariance under positive price scaling after point/tick normalization.
- Every feature-bearing record stores canonical JSON, feature hash, and reconstruction hash.

## 6. Classical Price Action ontology

Every definition is independent. Passing one definition does not imply another passed. No definition is ranked or selected as preferred.

### PA1 — Candle Anatomy Candidate

One immutable candidate per eligible closed bar, containing raw and normalized anatomy. Availability equals the bar availability.

### PA2 — Inside Bar

Current high is less than or equal to prior high and current low is greater than or equal to prior low. Store strict and edge-equality variants separately. Availability begins after the current bar closes.

### PA3 — Outside Bar

Current high is greater than or equal to prior high and current low is less than or equal to prior low. Store strict and edge-equality variants separately.

### PA4 — Engulfing

Independent variants:

- body-engulfing: current real body fully contains the prior real body;
- directional body-engulfing: body-engulfing plus opposing prior/current candle directions;
- full-range engulfing: current high-low range fully contains the prior high-low range.

Do not merge these variants.

### PA5 — Doji-like Candle

Independent locked variants based on body-to-range ratio:

- strict: `body_to_range <= 0.10`;
- broad: `body_to_range <= 0.20`.

A zero-range bar is stored as a separate data-quality/degenerate candidate and cannot pass a ratio-based pattern.

### PA6 — Pin-bar-like / Rejection Candle

Independent mechanical variants:

- dominant-wick variant: dominant wick / range >= 0.60, body / range <= 0.30, opposite wick / range <= 0.15;
- rejection-close variant: rejection wick / range >= 0.50 and close lies in the opposite outer quartile;
- context-linked rejection: one mechanical rejection variant plus a causally available overlap or proximity relation to an upstream zone, liquidity object, imbalance, or institutional zone.

These are shape/context records, not proof of intent or reversal.

### PA7 — Breakout Candidate

A breakout candidate exists only relative to a causally available upstream boundary or range object. Independent variants:

- exact close-through: closed price strictly beyond the boundary;
- point-buffer close-through: close beyond boundary by the frozen symbol-aware minimum increment;
- ATR-buffer close-through: close beyond boundary by the frozen descriptive ATR fraction.

Each variant remains separate. Wick-only breach is not close-through.

### PA8 — Failed Breakout

Derived only after an already-available breakout candidate and a later closed bar returns through the locked boundary into the prior range/zone. Availability is the later failure close. Preserve the original breakout candidate unchanged.

### PA9 — Retest

Derived only after an already-available breakout candidate. A later bar must causally revisit the broken boundary or locked tolerance band after at least one non-overlap bar. Store touch, penetration, close-side, duration, and right-censoring. Retest is descriptive and does not imply continuation.

### PA10 — Pullback

A pullback hypothesis requires a causally available Group 3 structural direction or Group 2 regime context, a counter-directional price movement, and no already-available invalidation of the referenced protected structure. Store depth, duration, overlap, volatility normalization, upstream zone/FVG/block relations, and ambiguity.

### PA11 — Continuation Hypothesis

A continuation hypothesis may be supported by causal combinations of:

- active upstream structural direction;
- same-direction displacement;
- breakout and optional retest;
- directional close location;
- reduced counter-directional overlap;
- causally available liquidity, FVG, zone, and block relations.

It is a narrative hypothesis, not a trade decision. Mandatory evidence is defined per school interpretation and stored explicitly.

### PA12 — Exhaustion Hypothesis

An exhaustion hypothesis may be supported by causal combinations of:

- declining normalized range/body or displacement quality;
- increasing opposing wick or overlap;
- repeated failed close-through;
- liquidity sweep/reclaim or failed breakout evidence;
- conflict between price extension and causally available structure/regime context.

No future reversal is used as evidence.

## 7. Dow / structural interpretation

Dow interpretations consume Group 3 only; Group 8 does not detect swings or structural breaks.

Required school-local hypotheses include:

- advancing structure;
- declining structure;
- range or indeterminate structure;
- continuation after causally available BOS;
- possible transition after causally available CHOCH/MSS;
- failed structural break interpretation;
- pullback within active protected structure;
- structural contradiction when upstream states/events disagree across timeframes.

Every interpretation stores the exact Group 3 IDs and their availability times. A Dow interpretation cannot exist when the required upstream structure evidence is absent; it must record missing evidence rather than infer it from raw price.

## 8. Wyckoff hypothesis layer

Wyckoff records are explicitly hypotheses, never assertions of institutional intent.

Possible hypothesis components:

- preliminary support/supply candidate;
- selling/buying climax candidate;
- automatic reaction/rally candidate;
- secondary test candidate;
- spring or upthrust candidate;
- test after spring/upthrust;
- sign of strength/weakness candidate;
- last point of support/supply candidate;
- accumulation, distribution, re-accumulation, re-distribution, or indeterminate phase hypothesis.

Mandatory constraints:

- range boundaries must reference causally available Group 3/4 objects;
- liquidity sweep/reclaim semantics must reference Group 5 IDs;
- displacement/imbalance semantics must reference Group 6 IDs;
- block semantics must reference Group 7 candidates/matches/zones without choosing a preferred definition;
- volume-based evidence is optional and may be used only when exact Group 1 volume provenance and field semantics pass dependency audit;
- absent or unreliable volume produces an explicit evidence-availability flag, not substituted synthetic volume;
- phase and event hypotheses remain independently testable and may conflict.

## 9. ICT / SMC interpretation layer

ICT/SMC interpretations are relations over frozen upstream objects:

- Group 3: BOS, CHOCH, MSS, protected structure, swings;
- Group 4: support/resistance, supply/demand and reference zones;
- Group 5: liquidity pools, equal highs/lows, sweeps, reclaims, stop runs, inducement, draw-on-liquidity;
- Group 6: displacement, FVG, imbalance variants, liquidity void, BPR, CE, inversion evidence and lifecycle;
- Group 7: independent block candidates, matches, zones, evidence and lifecycle.

Permitted hypotheses include:

- liquidity sweep plus displacement narrative;
- structural shift plus imbalance-delivery narrative;
- premium/discount location relative to a frozen causally available dealing-range reference;
- return-to-FVG, CE, BPR, void, or block context;
- breaker/mitigation/rejection/propulsion contextual relations;
- draw-on-liquidity narrative;
- conflicting liquidity/structure/delivery narrative.

Prohibitions:

- no new OB, FVG, liquidity-pool, BOS, CHOCH, MSS, inducement, breaker, or mitigation detection;
- no preferred Group 7 block definition;
- no statement of smart-money intent as fact;
- no entry model or execution sequence.

## 10. Multi-school interpretation

Each school interpretation is independent and immutable at creation.

### 10.1 Shared evidence

A `shared_evidence` record links two or more school interpretations only when they reference the same immutable upstream evidence ID or an explicitly stored deterministic relation over the same source geometry.

Shared evidence does not imply agreement in conclusion.

### 10.2 Conflicting evidence

A `conflicting_evidence` record is required when:

- two active school hypotheses make incompatible descriptive claims over the same time/location scope;
- one school requires evidence that another school marks as contradictory;
- timeframe interpretations oppose each other;
- a later causal event contradicts an active hypothesis without yet satisfying its locked invalidation rule.

No voting, averaging, winner selection, or preferred-school label is permitted.

### 10.3 Ambiguity

Every interpretation and hypothesis stores:

- mandatory evidence complete/incomplete;
- ambiguous flag;
- uncertainty reasons;
- missing upstream evidence IDs/types;
- supporting evidence count by type;
- contradicting evidence count by type;
- descriptive evidence-strength vector.

The evidence-strength vector is not a trade score and cannot be collapsed into a global setup rank.

## 11. Narrative hypotheses and lifecycle

Creation records are immutable. Lifecycle is append-only.

Locked lifecycle states:

1. `candidate` — intrinsic definition passed, but mandatory school evidence may be incomplete;
2. `active_supported` — exact mandatory evidence is available;
3. `active_ambiguous` — support and conflict coexist without invalidation;
4. `contradicted` — a causal contradiction exists but the locked invalidation condition has not completed;
5. `invalidated` — the explicit school-local invalidation rule completed;
6. `completed_descriptive` — the narrative's defined descriptive sequence completed without implying profitability;
7. `right_censored` — data ended while still active.

No arbitrary fixed-bar expiration is allowed. A school-specific time-window definition may exist only as an independently named variant and must be justified, frozen, and tested without future-return calibration.

## 12. Multi-timeframe relations

Run every timeframe independently before creating cross-timeframe relations.

Permitted relation types include:

- contained;
- partial overlap;
- same-direction context;
- opposing-direction context;
- HTF parent / LTF refinement;
- structural agreement;
- structural conflict;
- school agreement;
- school conflict;
- unavailable-at-LTF-time.

Availability equals the maximum availability of all related objects. No HTF relation may be backdated to an earlier LTF bar.

## 13. Mandatory persistent tables

At minimum:

- `metadata`;
- `config_registry`;
- `dataset_registry`;
- `dependency_registry`;
- `school_registry`;
- `pattern_definition_registry`;
- `interpretation_definition_registry`;
- `price_action_pattern_candidate`;
- `price_action_pattern_state`;
- `school_interpretation`;
- `shared_evidence`;
- `conflicting_evidence`;
- `narrative_hypothesis`;
- `hypothesis_lifecycle_event`;
- `multi_timeframe_context_relation`;
- `evidence_chain`;
- `invalidation_record`;
- `group8_audit_evidence`;
- `processing_checkpoint`.

Every feature-bearing or evidence-bearing table stores deterministic ID, symbol, timeframe, event/confirmation/availability times as applicable, upstream IDs, canonical payload, engine/schema/config identity, feature/evidence hash, and reconstruction hash.

## 14. Deterministic identity and duplicate contract

- IDs are SHA-256-derived from canonical creation payloads and immutable upstream identities.
- Future lifecycle outcomes are excluded from creation IDs.
- Exact duplicate import inserts zero records.
- Same deterministic ID with different canonical hash raises an explicit conflict error.
- Upstream IDs are never renamed or regenerated.
- Batch, streaming, restart/checkpoint, prefix, future-append, and full rebuild paths must produce identical creation IDs and hashes.

## 15. Required test matrix

### 15.1 Schema and dependency

- required tables and columns;
- config/engine/schema/lineage identities;
- repository and database SHA-256;
- SQLite quick/integrity/foreign-key checks;
- read-only dependency enforcement;
- legacy/superseded artifact rejection;
- missing dependency and partial database rejection;
- exact adapter-map hash reconstruction.

### 15.2 Pattern boundaries

- zero-range bar;
- exact edge equality;
- strict versus broad inside/outside variants;
- body versus full-range engulfing;
- doji thresholds immediately below/equal/above boundary;
- dominant-wick and close-location thresholds;
- breakout exact, point-buffer, ATR-buffer boundaries;
- wick breach without close-through;
- failed-breakout and retest ordering;
- missing ATR warm-up;
- absent/invalid volume.

### 15.3 Causality

- no look-ahead;
- no backdating;
- availability equals mandatory evidence maximum;
- HTF unfinished-bar isolation;
- later evidence appends without rewriting creation;
- contradiction before invalidation;
- right-censoring;
- no lifecycle event before hypothesis availability.

### 15.4 Determinism and persistence

- deterministic IDs and hashes;
- idempotent exact re-import;
- conflicting duplicate rejection;
- batch/stream parity;
- checkpoint/restart parity;
- prefix/future-append stability;
- database interruption recovery;
- stable reconstruction under row-order variation;
- foreign-key and orphan checks.

### 15.5 Multi-school and MTF

- shared evidence with differing conclusions;
- direct school conflict;
- ambiguous support/conflict coexistence;
- missing mandatory upstream evidence;
- school interpretation without prohibited rediscovery;
- MTF alignment and opposition;
- HTF availability lag;
- no preferred-school selection;
- no preferred Group 7 block definition.

### 15.6 Robustness

- positive price-scale invariance;
- point/tick-size normalization;
- small-noise stability away from thresholds;
- expected instability exactly at frozen thresholds;
- timezone representation stability with identical UTC epochs;
- missing-bar and data-gap handling;
- extreme volatility and near-zero volatility;
- threshold perturbation report for descriptive sensitivity only.

### 15.7 Prohibited-output audit

Search schema, code, reports, and database values for prohibited trading/PnL outputs and fail on any unauthorized field or semantic behavior.

## 16. Annual validation protocol

Only after technical candidate PASS and dependency intake PASS:

1. Build full 2023 Group 8 database using frozen design/config.
2. Review schema, causality, deterministic reconstruction, distributions, lifecycle consistency, false/ambiguous cases, and real visual evidence.
3. Perform gap analysis and fixes using 2023 only.
4. Freeze engine, schema, config, definitions, adapters, and thresholds.
5. Run untouched 2024 out-of-sample.
6. Do not change thresholds or definitions after inspecting 2024.
7. Compare 2023/2024 descriptively: definition coverage, school coverage, ambiguity/conflict rates, lifecycle distributions, causality errors, reconstruction and robustness gates.
8. Complete annual visual audits for both years, including valid, false, ambiguous, conflicting-school, MTF, and right-censored cases.
9. Complete independent audit and final verification.
10. Publish immutable annual identities and next-group dependency manifest.

No profitability criterion is permitted at any stage.

## 17. Mandatory execution loop

`Dependency Intake PASS → Design Lock Freeze → Build → Tests → Review → Gap Analysis → Fix → Retest → Independent Audit → 2023 Annual Build/Review → Frozen 2024 OOS → Cross-Year Validation → Annual Visual Audit → Final Verification → Official Closure`

A technical candidate may pass before annual closure. The verdict `Group 8 officially closed` is forbidden until every gate above passes and all final artifacts are published and independently verifiable.

Group 9 is forbidden before explicit official Group 8 closure.
