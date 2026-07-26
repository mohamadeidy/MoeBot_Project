#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

CANON_SEPARATORS = (",", ":")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=CANON_SEPARATORS, ensure_ascii=False, allow_nan=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_hash(value: Any) -> str:
    return sha256_text(canonical_json(value))


def deterministic_id(prefix: str, payload: Any) -> str:
    return f"{prefix}_{canonical_hash(payload)}"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def open_ro(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.resolve().as_posix()}?mode=ro&immutable=1"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def open_rw(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=rwc", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA temp_store=FILE")
    con.execute("PRAGMA cache_size=-262144")
    return con


def sqlite_integrity(path: Path) -> dict[str, Any]:
    con = open_ro(path)
    try:
        quick = con.execute("PRAGMA quick_check").fetchone()[0]
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        fk = con.execute("PRAGMA foreign_key_check").fetchall()
        return {
            "quick_check": quick,
            "integrity_check": integrity,
            "foreign_key_errors": len(fk),
            "pass": quick == "ok" and integrity == "ok" and not fk,
        }
    finally:
        con.close()


def safe_float(v: Any) -> float | None:
    if v is None:
        return None
    x = float(v)
    if not math.isfinite(x):
        return None
    return x


def max_time(*values: Any) -> int:
    ints = [int(v) for v in values if v is not None]
    if not ints:
        raise ValueError("max_time requires at least one non-null value")
    return max(ints)


@dataclass(frozen=True)
class BarFeature:
    bar_id: int
    symbol: str
    timeframe: str
    open_time: int
    close_time: int
    available_at: int
    open: float
    high: float
    low: float
    close: float
    prev_bar_id: int | None
    prev_close: float | None
    full_range: float
    body: float
    body_lower: float
    body_upper: float
    upper_wick: float
    lower_wick: float
    body_to_range: float | None
    upper_wick_to_range: float | None
    lower_wick_to_range: float | None
    open_location: float | None
    close_location: float | None
    true_range: float
    atr: float | None
    range_to_atr: float | None
    body_to_atr: float | None
    overlap_with_previous: float | None
    direction: str
    content_hash: str


def true_range(high: float, low: float, prev_close: float | None) -> float:
    if prev_close is None:
        return max(0.0, high - low)
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def wilder_atr(trs: Sequence[float], period: int) -> list[float | None]:
    if period <= 0:
        raise ValueError("period must be positive")
    out: list[float | None] = [None] * len(trs)
    if len(trs) < period:
        return out
    atr = sum(trs[:period]) / period
    out[period - 1] = atr
    for i in range(period, len(trs)):
        atr = ((atr * (period - 1)) + trs[i]) / period
        out[i] = atr
    return out


def build_bar_features(rows: Sequence[Mapping[str, Any]], atr_period: int) -> list[BarFeature]:
    if not rows:
        return []
    trs: list[float] = []
    prev_close: float | None = None
    for row in rows:
        h, l = float(row["high"]), float(row["low"])
        trs.append(true_range(h, l, prev_close))
        prev_close = float(row["close"])
    atrs = wilder_atr(trs, atr_period)
    result: list[BarFeature] = []
    prev: Mapping[str, Any] | None = None
    for idx, row in enumerate(rows):
        o, h, l, c = map(float, (row["open"], row["high"], row["low"], row["close"]))
        rng = max(0.0, h - l)
        body = abs(c - o)
        body_lo, body_hi = min(o, c), max(o, c)
        uw = max(0.0, h - body_hi)
        lw = max(0.0, body_lo - l)
        atr = atrs[idx]
        if rng > 0:
            body_r = body / rng
            uw_r = uw / rng
            lw_r = lw / rng
            open_loc = (o - l) / rng
            close_loc = (c - l) / rng
        else:
            body_r = uw_r = lw_r = open_loc = close_loc = None
        overlap = None
        if prev is not None:
            overlap_len = max(0.0, min(h, float(prev["high"])) - max(l, float(prev["low"])))
            denom = max(rng, float(prev["high"]) - float(prev["low"]))
            overlap = overlap_len / denom if denom > 0 else None
        direction = "bullish" if c > o else "bearish" if c < o else "neutral"
        result.append(BarFeature(
            bar_id=int(row["id"]), symbol=str(row["symbol"]), timeframe=str(row["timeframe"]),
            open_time=int(row["open_time"]), close_time=int(row["close_time"]), available_at=int(row["available_at"]),
            open=o, high=h, low=l, close=c,
            prev_bar_id=int(prev["id"]) if prev is not None else None,
            prev_close=float(prev["close"]) if prev is not None else None,
            full_range=rng, body=body, body_lower=body_lo, body_upper=body_hi,
            upper_wick=uw, lower_wick=lw,
            body_to_range=body_r, upper_wick_to_range=uw_r, lower_wick_to_range=lw_r,
            open_location=open_loc, close_location=close_loc, true_range=trs[idx], atr=atr,
            range_to_atr=(rng / atr if atr and atr > 0 else None),
            body_to_atr=(body / atr if atr and atr > 0 else None),
            overlap_with_previous=overlap, direction=direction, content_hash=str(row["content_hash"]),
        ))
        prev = row
    return result


def pattern_flags(cur: BarFeature, prev: BarFeature | None, config: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    th = config["pattern_thresholds"]
    out: dict[str, dict[str, Any]] = {}
    degenerate = cur.full_range <= 0
    out["pa_candle_anatomy"] = {"pass": True, "direction": cur.direction, "ambiguous": degenerate}
    if prev is not None:
        out["pa_inside_bar_strict"] = {"pass": cur.high < prev.high and cur.low > prev.low, "direction": cur.direction, "ambiguous": False}
        out["pa_inside_bar_edge"] = {"pass": cur.high <= prev.high and cur.low >= prev.low, "direction": cur.direction, "ambiguous": False}
        out["pa_outside_bar_strict"] = {"pass": cur.high > prev.high and cur.low < prev.low, "direction": cur.direction, "ambiguous": False}
        out["pa_outside_bar_edge"] = {"pass": cur.high >= prev.high and cur.low <= prev.low, "direction": cur.direction, "ambiguous": False}
        body_engulf = cur.body_lower <= prev.body_lower and cur.body_upper >= prev.body_upper and cur.body > 0
        out["pa_body_engulfing"] = {"pass": body_engulf, "direction": cur.direction, "ambiguous": False}
        out["pa_directional_body_engulfing"] = {
            "pass": body_engulf and cur.direction in {"bullish", "bearish"} and prev.direction in {"bullish", "bearish"} and cur.direction != prev.direction,
            "direction": cur.direction, "ambiguous": False,
        }
        out["pa_full_range_engulfing"] = {"pass": cur.high >= prev.high and cur.low <= prev.low, "direction": cur.direction, "ambiguous": False}
    if not degenerate and cur.body_to_range is not None:
        out["pa_doji_strict"] = {"pass": cur.body_to_range <= float(th["doji_strict_body_to_range_max"]), "direction": "neutral", "ambiguous": False}
        out["pa_doji_broad"] = {"pass": cur.body_to_range <= float(th["doji_broad_body_to_range_max"]), "direction": "neutral", "ambiguous": False}
        dominant = max(cur.lower_wick, cur.upper_wick)
        opposite = min(cur.lower_wick, cur.upper_wick)
        dominant_ratio = dominant / cur.full_range
        opposite_ratio = opposite / cur.full_range
        pin_pass = (
            dominant_ratio >= float(th["pin_dominant_wick_to_range_min"])
            and cur.body_to_range <= float(th["pin_body_to_range_max"])
            and opposite_ratio <= float(th["pin_opposite_wick_to_range_max"])
        )
        pin_dir = "bullish" if cur.lower_wick > cur.upper_wick else "bearish" if cur.upper_wick > cur.lower_wick else "ambiguous"
        out["pa_pin_bar_like"] = {"pass": pin_pass, "direction": pin_dir, "ambiguous": pin_dir == "ambiguous"}
        outer = float(th["rejection_close_outer_fraction"])
        lower_rej = cur.lower_wick / cur.full_range >= float(th["rejection_wick_to_range_min"]) and cur.close_location is not None and cur.close_location >= 1.0 - outer
        upper_rej = cur.upper_wick / cur.full_range >= float(th["rejection_wick_to_range_min"]) and cur.close_location is not None and cur.close_location <= outer
        rej_pass = lower_rej or upper_rej
        rej_dir = "bullish" if lower_rej and not upper_rej else "bearish" if upper_rej and not lower_rej else "ambiguous"
        out["pa_rejection_close"] = {"pass": rej_pass, "direction": rej_dir, "ambiguous": lower_rej and upper_rej}
    return out


def chunks(seq: Sequence[Any], n: int = 5000) -> Iterator[Sequence[Any]]:
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def execute_many(con: sqlite3.Connection, sql: str, rows: Iterable[Sequence[Any]], batch: int = 5000) -> int:
    count = 0
    buf: list[Sequence[Any]] = []
    for row in rows:
        buf.append(row)
        if len(buf) >= batch:
            con.executemany(sql, buf)
            count += len(buf)
            buf.clear()
    if buf:
        con.executemany(sql, buf)
        count += len(buf)
    return count
