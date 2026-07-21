# Group 6 — Imbalance, FVG & Delivery: Frozen Design Lock

## Prerequisite and dependency contract

Group 5 is closed. Groups 2–5 are read-only dependencies. Group 6 must not modify or rediscover their regime, structure, zone, or liquidity logic.

## Objective

Build a causal and auditable intelligence layer for displacement, classic FVG, separated imbalance variants, liquidity voids, Balanced Price Ranges, Consequent Encroachment, fill/mitigation/inversion lifecycle, multi-timeframe relations, and evidence links to Groups 2–5. Group 6 does not trade and emits no BUY/SELL/WAIT, entry, SL, TP, or profitability optimization.

## Displacement

Detect bullish/bearish candidates, single-candle and multi-candle legs, validated and uncertain displacement. Measure body/ATR, range/ATR, body-to-range, closing location, wick ratios, net movement, bar count, duration, speed, overlap, compression departure, FVG/void creation, Group 3 BOS/MSS evidence, and Group 5 liquidity evidence. Preserve event, confirmation, and availability times. Historical leg records are immutable; later evidence is appended through `displacement_validation_events`.

## Neutral origin references — mandatory

Every displacement leg stores an origin bar ID, origin window, body range, wick range, full range, base duration, first impulse bar, last opposing candle reference, and causal evidence IDs for resulting FVGs, BOS/MSS/CHOCH, liquidity events/pools, and liquidity voids. The only permitted origin label is `origin_reference_only_not_order_block`. Group 6 must never classify an origin as an Order Block or select a preferred Order Block definition.

## Classic FVG

Bullish: candle 3 low > candle 1 high. Bearish: candle 3 high < candle 1 low. Exact equality is not an FVG. Availability begins only after candle 3 closes. Store bounds, direction, times, absolute/point/ATR size, CE at 50%, associated leg, Group 3 and Group 5 evidence, Group 4 parent zones, Group 2 context, and formation quality.

## Separated imbalance variants

Classic wick-to-wick FVG, body-imbalance candidate, opening gap, session gap, weekend gap, broker/data gap, and missing-bar discontinuity remain separate records. Data/history gaps must never be labelled market FVGs.

## Lifecycle

Store immutable transitions: Created → Untouched → First touched → Partially filled → CE reached → Fully filled → Traversed, plus directional validity and inversion candidate/retest evidence. Preserve first touch, maximum penetration, fill percentage, CE/full/traverse times, visit count, mitigation delay, visit exits, right-censoring, and reactions after visits. Fill state is separate from directional validity. No arbitrary fixed-bar expiry is allowed.

## Liquidity Void, BPR, and inversion

A liquidity void requires a directional low-overlap cluster with multiple FVG members and strong delivery; one FVG alone is not a void. A BPR requires causal overlap between already-available opposing FVGs. IFVG is derived only after explicit close-through/traverse evidence and may add retest observations; a filled FVG is not automatically an IFVG.

## Multi-timeframe mapping

Run every timeframe independently, then store causal contained/partial/nested/same-direction/opposing and HTF-parent/LTF-child relations. No HTF object may be available on an LTF before its own confirmation close. HTF provides context and LTF provides refinement only.

## Output tables

At minimum: `displacement_legs`, `displacement_validation_events`, `fvg_events`, `fvg_state_transitions`, `fvg_visit_observations`, `fvg_visit_reactions`, `fvg_lifecycle_summary`, `imbalance_variants`, `liquidity_voids`, `liquidity_void_members`, `liquidity_void_state_transitions`, `liquidity_void_lifecycle_summary`, `bpr_relations`, `bpr_state_transitions`, `bpr_lifecycle_summary`, `inversion_fvg_relations`, `inversion_retest_observations`, `mtf_imbalance_relations`, `group6_evidence`, and `group6_audit_evidence`.

## Mandatory tests and closure

Synthetic clean/boundary/false/gap/lifecycle/BPR/void/unfinished-HTF cases; no-look-ahead; no repaint; batch–streaming; restart/checkpoint; future append; prefix; idempotence; duplicate/conflicting input; missing bar; timezone shift; scale; noise; threshold perturbation; MTF alignment; SQLite/foreign keys; deterministic ID/hash reconstruction; real visual audit including difficult and false cases; independent audit; 2023 validation; frozen 2024 out-of-sample validation; cross-year validation. Group 7 may not start before the explicit verdict `Group 6 officially closed`.
