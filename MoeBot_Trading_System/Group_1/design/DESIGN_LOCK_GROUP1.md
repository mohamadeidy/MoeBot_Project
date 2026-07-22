# Design Lock — Group 1: Data Integrity & Market Memory

- **Lock ID:** DL-G1-2.3
- **Implementation candidate:** 0.9.1
- **Spool schema:** 1.4.0
- **Database schema:** 2.3.0
- **State:** locally verified; locked for exact-source native validation.

## 1. Scope

Group 1 acquires, preserves, validates, indexes, reconstructs, and renders market evidence. It never interprets the evidence as a trading setup.

Explicitly excluded:

- regime, BOS, CHOCH, MSS, liquidity, inducement, FVG, order-block, setup, or policy inference;
- signals, entries, exits, stops, targets, risk sizing, news filtering, optimization, or orders;
- live self-training or direct model updates.

## 2. MT5 acquisition boundary

The collector shall:

- recover ticks with `CopyTicksRange`, millisecond cursor, and ordinal for equal-millisecond ticks;
- advance tick and bar checkpoints only after `FileFlush`;
- capture only closed M1/M5/M15/M30/H1/H4/D1 bars;
- preserve original server epochs and all available price, spread, volume, and flag fields;
- collect symbol metadata and broker trade sessions;
- poll clock evidence every timer event and persist initial, heartbeat, offset-change, backward-clock, and final samples;
- create an isolated `run_id` and completion marker;
- close a completed raw run folder at each GMT-day boundary by default without resetting market cursors;
- contain no trading interface or order operation;
- write append-oriented raw spool evidence, not the authoritative research database.

## 3. Python memory boundary

The Python layer shall:

- reject incompatible spool or database schemas;
- isolate a market stream by broker/company, account server, symbol, and source;
- separate canonical market facts from run-specific observations;
- preserve raw-line SHA-256 lineage;
- import by durable byte checkpoint with sequence-contiguity guards;
- be idempotent under a complete source re-scan;
- preserve raw server time and keep derived UTC run-owned;
- refuse external UTC authority for Strategy Tester clock evidence;
- inventory temporal gaps without manufacturing bars during no-tick intervals;
- build causal decision snapshots and physically separate later labels;
- provide quick operational and full identity/integrity verification.

## 4. Identity lock

### Market stream

`broker/company + account server + symbol + source`

Account login scopes collector run/checkpoint identity but is not part of feed canonicalization. Separate accounts on the same feed may share canonical market facts while retaining separate observations.

### Tick

Canonical tick identity includes stream, server millisecond, equal-millisecond ordinal, scaled bid/ask/last, volume, real volume, and flags. It excludes run ID, observation time, and derived UTC.

### Bar

Canonical bar identity includes stream, timeframe, raw server open/close, scaled OHLCV/spread, and closed status. Broker revisions remain separate canonical versions; snapshots select the newest eligible observation without deleting prior evidence.

### Observation

An observation belongs to one run and stores acquisition order/time, offset evidence, confidence, and raw-line SHA-256. Internal integer keys reduce storage, while full deterministic IDs remain stored and verified.

## 5. Causality lock

- Closed bars only.
- `available_at` and `observed_at` must be at or before decision time.
- Whole-second collector observation precision permits a tick millisecond within the same observed second, but not a later second.
- Future labels are stored separately from decision snapshots.
- Time reconciliation adds derived fields only; raw server epochs are immutable.
- DST fallback ambiguity remains unresolved rather than guessed.
- Tester clock can order records internally but cannot align external news or global sessions as verified UTC.

## 6. Gap semantics lock

- A temporal discontinuity is first compared with broker sessions.
- If all absent slots are outside the recorded session, it is `expected_session_gap`.
- If a slot is nominally open but the same run has no tick in the absent range, it is `expected_no_tick_gap`; MT5 does not form an OHLC bar without a quote.
- If run-specific tick evidence exists inside a missing bar range, it is `unexpected_gap` and remains open for investigation.
- No synthetic OHLC bar is created.

## 7. Durability and storage lock

- Active raw files are bounded by daily run rotation by default.
- Tick and bar cursors survive rotation and restart.
- Ticks arriving during rotation are recovered with `CopyTicksRange`.
- Completed runs may be sealed, verified, and ZIP archived; source deletion is never automatic.
- SQLite commits by batch and records source fingerprint, byte offset, row count, last sequence, and completion state.
- A changed source after checkpoint is rejected.
- Group 1 does not discard tick evidence merely to reduce size.

## 8. Acceptance criteria

### Local candidate gates

1. all automated tests pass;
2. Python compileall passes;
3. MQL static audit finds no trading operation;
4. sealed-spool tamper detection passes;
5. real-source import count equals source count;
6. complete second import inserts zero new records;
7. quick and full database verification pass;
8. gap inventory contains no uninvestigated tick-backed missing bar;
9. causal snapshot renders from stored data;
10. clean wheel build and isolated installation pass;
11. release manifest and checksums match delivered files.

### Native closure gates

1. exact-source MetaEditor compile with 0 errors and 0 warnings;
2. real daily rotation with no lost tick/bar;
3. restart and disconnect recovery checked against MT5 history;
4. real broker UTC/DST transition validated;
5. extended VPS and archive workflow validated.

Until the native gates pass, this is a candidate rather than a 100% closed Group 1.
