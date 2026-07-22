#!/usr/bin/env python3
"""Build a deterministic MoeBot source SQLite database from public Dukascopy XAU/USD BID M1 candles.

This is a new, independently versioned rebuild lineage. It does not claim byte identity
with the unavailable historical Group 1/Collector SQLite files.
"""
from __future__ import annotations

import argparse
import calendar
import datetime as dt
import hashlib
import json
import math
import os
import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

PROVIDER = "Dukascopy Jetta public candles API"
API_ROOT = "https://jetta.dukascopy.com/v1"
INSTRUMENT_CODE = "XAU-USD"
SYMBOL = "XAUUSD_"
PRICE_TYPE = "BID"
REBUILD_VERSION = "dukascopy_rebuild_v1"
SCHEMA_VERSION = "moebot_source_rebuild_1.0.0"
TF_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}
TF_CODE = {"M1": 1, "M5": 2, "M15": 3, "M30": 4, "H1": 5, "H4": 6, "D1": 7}


@dataclass(frozen=True)
class Candle:
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def fetch_json(url: str, cache_path: Path, retries: int = 6) -> dict[str, Any] | None:
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": "MoeBot-Data-Vault/1.0 (+https://github.com/mohamadeidy/MoeBot_Project)", "Accept": "application/json"}
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=90) as response:
                payload = response.read()
            if not payload:
                return None
            data = json.loads(payload)
            temp = cache_path.with_suffix(cache_path.suffix + ".tmp")
            temp.write_bytes(payload)
            temp.replace(cache_path)
            return data
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 204):
                return None
            if attempt + 1 >= retries:
                raise
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            if attempt + 1 >= retries:
                raise
        time.sleep(min(60, 2 ** attempt))
    raise RuntimeError(f"Unable to fetch {url}")


def decode_candles(data: dict[str, Any]) -> Iterator[Candle]:
    required = ("timestamp", "multiplier", "shift", "times", "open", "high", "low", "close", "opens", "highs", "lows", "closes", "volumes")
    missing = [key for key in required if key not in data]
    if missing:
        raise ValueError(f"Dukascopy response missing keys: {missing}")
    columns = [data["times"], data["opens"], data["highs"], data["lows"], data["closes"], data["volumes"]]
    length = len(data["times"])
    if any(not isinstance(col, list) or len(col) != length for col in columns):
        raise ValueError("Dukascopy response column lengths do not match")
    if length == 0:
        return
    multiplier = float(data["multiplier"])
    shift_ms = int(data["shift"])
    if multiplier <= 0 or shift_ms <= 0:
        raise ValueError("Invalid multiplier or shift")
    timestamp_ms = int(data["timestamp"])
    open_units = round(float(data["open"]) / multiplier)
    high_units = round(float(data["high"]) / multiplier)
    low_units = round(float(data["low"]) / multiplier)
    close_units = round(float(data["close"]) / multiplier)
    for i in range(length):
        delta = int(data["times"][i])
        if delta < 0:
            raise ValueError("Negative candle time delta")
        timestamp_ms += delta * shift_ms
        open_units += int(data["opens"][i])
        high_units += int(data["highs"][i])
        low_units += int(data["lows"][i])
        close_units += int(data["closes"][i])
        candle = Candle(
            open_time=timestamp_ms // 1000,
            open=round(open_units * multiplier, 8),
            high=round(high_units * multiplier, 8),
            low=round(low_units * multiplier, 8),
            close=round(close_units * multiplier, 8),
            volume=float(data["volumes"][i]),
        )
        if not all(math.isfinite(x) for x in (candle.open, candle.high, candle.low, candle.close, candle.volume)):
            raise ValueError("Non-finite candle value")
        if candle.low <= 0 or candle.low > min(candle.open, candle.close) or candle.high < max(candle.open, candle.close):
            raise ValueError(f"Invalid OHLC candle at {candle.open_time}: {candle}")
        yield candle


def bar_hash(tf: str, open_time: int, close_time: int, o: float, h: float, l: float, c: float, volume: int) -> bytes:
    material = canonical_json({
        "symbol": SYMBOL, "timeframe": tf, "open_time": open_time, "close_time": close_time,
        "open": round(o, 8), "high": round(h, 8), "low": round(l, 8), "close": round(c, 8),
        "tick_volume": volume, "spread_points": 0, "provider": "dukascopy", "price_type": PRICE_TYPE,
        "rebuild_version": REBUILD_VERSION,
    })
    return hashlib.sha256(material.encode("utf-8")).digest()


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    PRAGMA foreign_keys=ON;
    CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE source_days(
      day_utc TEXT PRIMARY KEY,
      endpoint TEXT NOT NULL,
      cache_sha256 TEXT,
      observed_rows INTEGER NOT NULL,
      status TEXT NOT NULL
    );
    CREATE TABLE bars(
      id INTEGER PRIMARY KEY,
      symbol TEXT NOT NULL,
      timeframe TEXT NOT NULL,
      open_time INTEGER NOT NULL,
      close_time INTEGER NOT NULL,
      available_at INTEGER NOT NULL,
      open_time_server INTEGER NOT NULL,
      close_time_server INTEGER NOT NULL,
      open REAL NOT NULL,
      high REAL NOT NULL,
      low REAL NOT NULL,
      close REAL NOT NULL,
      tick_volume INTEGER NOT NULL,
      spread_points INTEGER NOT NULL,
      broker_offset_seconds INTEGER NOT NULL,
      time_confidence TEXT NOT NULL,
      source_run_id TEXT NOT NULL,
      content_hash BLOB NOT NULL,
      UNIQUE(symbol,timeframe,open_time)
    );
    CREATE INDEX idx_bars_tf_time ON bars(timeframe,open_time);
    CREATE INDEX idx_bars_symbol_tf_time ON bars(symbol,timeframe,open_time);
    CREATE VIEW canonical_bars AS
      SELECT id,symbol,timeframe,open_time AS open_time_server,close_time AS close_time_server,
             open,high,low,close,tick_volume,spread_points,lower(hex(content_hash)) AS content_hash
      FROM bars;
    """)


def insert_bar(conn: sqlite3.Connection, tf: str, sequence: int, candle: Candle, source_run_id: str) -> None:
    close_time = candle.open_time + TF_SECONDS[tf]
    volume = max(0, int(round(candle.volume)))
    conn.execute(
        "INSERT INTO bars VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (TF_CODE[tf] * 1_000_000_000 + sequence, SYMBOL, tf, candle.open_time, close_time, close_time,
         candle.open_time, close_time, candle.open, candle.high, candle.low, candle.close, volume, 0, 0,
         "provider_utc", source_run_id,
         bar_hash(tf, candle.open_time, close_time, candle.open, candle.high, candle.low, candle.close, volume))
    )


def download_m1(conn: sqlite3.Connection, year: int, cache_dir: Path) -> int:
    run_id = f"dukascopy-xauusd-bid-m1-{year}-{REBUILD_VERSION}"
    start_epoch = calendar.timegm((year, 1, 1, 0, 0, 0))
    end_epoch = calendar.timegm((year + 1, 1, 1, 0, 0, 0))
    seen: set[int] = set()
    sequence = 0
    day = dt.date(year, 1, 1)
    end_day = dt.date(year + 1, 1, 1)
    while day < end_day:
        url = f"{API_ROOT}/candles/minute/{INSTRUMENT_CODE}/{PRICE_TYPE}/{day.year}/{day.month}/{day.day}"
        cache_path = cache_dir / str(year) / f"{day.isoformat()}.json"
        data = fetch_json(url, cache_path)
        rows = 0
        if data:
            for candle in decode_candles(data):
                if candle.open_time < start_epoch or candle.open_time >= end_epoch or candle.open_time in seen:
                    continue
                seen.add(candle.open_time)
                sequence += 1
                insert_bar(conn, "M1", sequence, candle, run_id)
                rows += 1
        conn.execute("INSERT INTO source_days VALUES(?,?,?,?,?)", (
            day.isoformat(), url, sha256_file(cache_path) if cache_path.exists() else None, rows,
            "ok" if data is not None else "no_data"
        ))
        if day.day == 1 or day.day % 10 == 0:
            conn.commit()
        day += dt.timedelta(days=1)
    conn.commit()
    return sequence


def aggregate_timeframe(conn: sqlite3.Connection, tf: str, source_run_id: str) -> int:
    seconds = TF_SECONDS[tf]
    cursor = conn.execute("SELECT open_time,open,high,low,close,tick_volume FROM bars WHERE timeframe='M1' ORDER BY open_time")
    sequence = 0
    bucket: int | None = None
    agg: list[float] | None = None

    def flush() -> None:
        nonlocal sequence, agg, bucket
        if agg is None or bucket is None:
            return
        sequence += 1
        insert_bar(conn, tf, sequence, Candle(bucket, agg[0], agg[1], agg[2], agg[3], agg[4]), source_run_id)

    for open_time, o, h, l, c, volume in cursor:
        current_bucket = int(open_time) // seconds * seconds
        if bucket != current_bucket:
            flush()
            bucket = current_bucket
            agg = [float(o), float(h), float(l), float(c), float(volume)]
        else:
            assert agg is not None
            agg[1] = max(agg[1], float(h))
            agg[2] = min(agg[2], float(l))
            agg[3] = float(c)
            agg[4] += float(volume)
    flush()
    conn.commit()
    return sequence


def verify_source(conn: sqlite3.Connection, year: int) -> dict[str, Any]:
    quick = conn.execute("PRAGMA quick_check").fetchone()[0]
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    counts = {tf: conn.execute("SELECT count(*) FROM bars WHERE timeframe=?", (tf,)).fetchone()[0] for tf in TF_SECONDS}
    duplicates = conn.execute("SELECT count(*) FROM (SELECT symbol,timeframe,open_time,count(*) n FROM bars GROUP BY 1,2,3 HAVING n>1)").fetchone()[0]
    invalid_ohlc = conn.execute("SELECT count(*) FROM bars WHERE low>min(open,close) OR high<max(open,close) OR low<=0").fetchone()[0]
    out_of_year = conn.execute(
        "SELECT count(*) FROM bars WHERE open_time<? OR open_time>=?",
        (calendar.timegm((year,1,1,0,0,0)), calendar.timegm((year+1,1,1,0,0,0)))
    ).fetchone()[0]
    missing = [tf for tf, count in counts.items() if count == 0]
    result = {"quick_check": quick, "integrity_check": integrity, "counts": counts, "duplicates": duplicates,
              "invalid_ohlc": invalid_ohlc, "out_of_year": out_of_year, "missing_timeframes": missing}
    if quick != "ok" or integrity != "ok" or duplicates or invalid_ohlc or out_of_year or missing:
        raise RuntimeError(f"Source verification failed: {result}")
    return result


def build(year: int, output: Path, cache_dir: Path) -> dict[str, Any]:
    if output.exists():
        output.unlink()
    output.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(output)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=FILE")
    init_db(conn)
    metadata = {
        "rebuild_version": REBUILD_VERSION,
        "schema_version": SCHEMA_VERSION,
        "provider": PROVIDER,
        "api_root": API_ROOT,
        "instrument_code": INSTRUMENT_CODE,
        "symbol": SYMBOL,
        "price_type": PRICE_TYPE,
        "year": year,
        "time_basis": "UTC",
        "gap_policy": "preserve observed records; do not manufacture flat candles",
        "spread_policy": "BID-only public source; spread_points=0",
        "broker_offset_seconds": 0,
        "lineage_notice": "New public-data rebuild; not byte-identical to unavailable Collector databases",
    }
    conn.executemany("INSERT INTO metadata VALUES(?,?)", [(k, canonical_json(v) if isinstance(v, (dict,list)) else str(v)) for k,v in metadata.items()])
    m1_count = download_m1(conn, year, cache_dir)
    if m1_count < 100_000:
        raise RuntimeError(f"Suspiciously low M1 count for {year}: {m1_count}")
    run_id = f"dukascopy-xauusd-bid-aggregated-{year}-{REBUILD_VERSION}"
    aggregate_counts = {tf: aggregate_timeframe(conn, tf, run_id) for tf in ("M5","M15","M30","H1","H4","D1")}
    verification = verify_source(conn, year)
    conn.execute("INSERT OR REPLACE INTO metadata VALUES(?,?)", ("verification_json", canonical_json(verification)))
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.execute("VACUUM")
    conn.close()
    return {"year": year, "output": str(output), "sha256": sha256_file(output), "size_bytes": output.stat().st_size,
            "m1_count": m1_count, "aggregate_counts": aggregate_counts, "verification": verification, "metadata": metadata}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True, choices=(2023, 2024))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache/dukascopy"))
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = build(args.year, args.output, args.cache_dir)
    text = json.dumps(report, indent=2, sort_keys=True)
    print(text)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
