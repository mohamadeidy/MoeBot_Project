# Group 8 Stage 6 Frozen-Definition Conformance Finding

Status: **IMPLEMENTATION BUG CONFIRMED / FROZEN SEMANTICS UNCHANGED**

The representative 2023 V3 preflight observed 93,834 bounded-range roots but 257,922,702 range/Dow pairs because the legacy Stage-6 query selected every historical `dow_indeterminate_structure` with `availability_time <= range availability`.

The frozen definition registry already requires:

- DOW1I.1: `causally_latest_group3_structure_state_per_layer`;
- WYC1.1: same-timeframe/layer indeterminate Dow structure and causal overlap.

Therefore the historical fan-out is not a required semantic property. It is a reference implementation defect.

Correction rule:

1. For each bounded range, use its exact frozen layer.
2. Consider only indeterminate Dow interpretations of the same symbol, timeframe and exact layer with availability <= range availability.
3. Select exactly the causally latest eligible interpretation, using the existing deterministic ordering for ties.
4. Preserve all frozen writers, definitions, thresholds, evidence payloads, IDs and row hashes.
5. Do not delete historical Dow rows; they remain valid historical evidence.
6. Re-run representative preflight before any annual Stage-6 authorization.

No Stage 7 launch is authorized by this finding.
