# Verification Report — Group 1 Candidate 0.9.1

## Scope

This candidate closes the local Data Integrity & Market Memory loop. It contains no trading interpretation or execution logic.

Versions:

- package/collector: `0.9.1`;
- raw spool schema: `1.4.0`;
- Market Memory database schema: `2.3.0`.

## Local deterministic suite

- Python compileall: passed;
- automated tests: **29 passed, 0 failed**;
- MQL static audit: passed;
- forbidden trading calls: none detected.

Evidence: `LOCAL_VERIFICATION_v0.9.1.txt` and `STATIC_AUDIT_RESULT.json`.

## Real supplied run

Raw sealed evidence:

- total raw bytes: **673,769,104**;
- ticks CSV: **656,784,477 bytes**;
- bars CSV: **16,125,857 bytes**;
- clock CSV: **857,268 bytes**;
- manifest ID: `manifest_fb1b7f779d4fd8be658fde7fb07118c0537e9ecb658b6fe2bdc812d58ef5882c`;
- manifest SHA-256: `7ddca36f7cb0ebd11a9ff5f09cbacec1c2cb69c04a952e7f0b8d3a97ee4337a0`;
- manifest verification: **passed**.

First import:

- ticks: **3,461,325 canonical + 3,461,325 observations**;
- bars: **64,749 canonical + 64,749 observations**;
- clock samples: **8,929**;
- symbol metadata: 1;
- sessions: 5;
- elapsed: **441.14 seconds**.

Complete second source re-scan:

- new ticks: **0**;
- duplicate tick observations recognized: **3,461,325**;
- new bars: **0**;
- duplicate bar observations recognized: **64,749**;
- elapsed: **335.72 seconds**.

This proves idempotence on the complete 656.8 MB tick source, not only on a fixture.

## Time handling

The supplied run is Strategy Tester data. Time reconciliation correctly returned:

- `skipped_untrusted_tester_clock = 1`;
- no externally trusted UTC normalization was created;
- raw server epochs remain available and immutable.

## Gap audit

Across all seven timeframes the inventory contains **623 temporal discontinuities**:

- **532** `expected_session_gap`;
- **91** `expected_no_tick_gap`;
- **0** `unexpected_gap` with run-specific tick evidence.

The no-tick classification is essential: MT5 does not create an OHLC bar when no quote arrives. No synthetic bars were manufactured.

## Full database verification

Full verification recomputed identities and executed SQLite integrity checks:

- result: **passed**;
- checks: **17/17 passed**;
- database bytes: **747,364,352**;
- database SHA-256: `aa0369b7323f17bea127ddf2914dc877c2d4e3ece3801b29fa2d3d7c4e517a40`;
- elapsed: **89.30 seconds**;
- maximum RSS: **305,744 KB**.

Verified properties include foreign keys, schema contracts, stream isolation, spread consistency, OHLC boundaries, causal observation time, sequence continuity, raw-line hash shape, tester-time isolation, checkpoint consistency, and complete tick/bar record-ID recomputation.

## Snapshot

A decision-only multi-timeframe snapshot was generated and registered:

- snapshot ID: `snapshot_218f4424bdde1edcea5a69601d76081e8fbc69b98bcb0ccb4f9f6cb796177726`;
- asset ID: `asset_c3ec8aa3959d40f7183722ab97475ae42d4428cbf3b3ceecf74e946fe8a58eae`;
- future labels were not included.

## Wheel and isolated install

- wheel: `moebot_market_memory-0.9.1-py3-none-any.whl`;
- isolated `--no-index --no-deps` install: passed;
- installed package version: 0.9.1;
- installed CLI spool verification: passed;
- installed CLI synthetic import and full database verification: passed.

## What is proven

- source code and local Python execution are internally consistent;
- real-month raw evidence is sealed and reproducible;
- import is resumable and idempotent;
- canonical data and run observations remain isolated;
- no tick-backed missing bar was found in the supplied run;
- Strategy Tester time is not promoted to external UTC;
- no trading operation exists.

## What remains native

The exact MQL source still requires:

1. MetaEditor compile with 0 errors and 0 warnings;
2. real daily rotation across a date boundary;
3. restart and disconnect recovery compared with MT5 history;
4. live/demo broker UTC and DST transition evidence;
5. extended VPS and archive workflow validation.

Therefore candidate 0.9.1 is locally verified but Group 1 is not yet declared 100% production-closed.

## Collector change-scope audit

Compared with the previously tested v0.6.1 collector core, these protected functions remain byte-for-byte identical:

- `WriteTickWithOrdinal`;
- `ProcessTickBatch`;
- `CaptureTicksRange`;
- `CaptureAvailableTicks`;
- `ExportBarsForTf`;
- `SaveTickCheckpoint`;
- `SaveCheckpoint`.

Intentional collector changes are limited to CSV safety, stronger run/checkpoint identity, sparse clock/run lifecycle, and daily folder rotation. Evidence: `CHANGE_SCOPE_AUDIT.json`.
