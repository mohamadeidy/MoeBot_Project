#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, sqlite3
from pathlib import Path

SOURCE_REQUIRED = {"bars", "metadata", "source_days"}
GROUP6_REQUIRED = {"metadata", "config_registry", "dataset_registry", "dependency_registry", "displacement_legs", "fvg_events", "fvg_lifecycle_summary", "imbalance_variants", "liquidity_voids", "bpr_relations", "group6_evidence"}


def verify(path: Path, kind: str) -> dict:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    quick = conn.execute("PRAGMA quick_check").fetchone()[0]
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    fk = conn.execute("PRAGMA foreign_key_check").fetchall()
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    required = SOURCE_REQUIRED if kind == "source" else GROUP6_REQUIRED
    missing = sorted(required - tables)
    detail = {"path": str(path), "kind": kind, "quick_check": quick, "integrity_check": integrity,
              "foreign_key_errors": len(fk), "missing_tables": missing, "table_count": len(tables)}
    if kind == "source" and "bars" in tables:
        detail["timeframe_counts"] = {tf: conn.execute("SELECT count(*) FROM bars WHERE timeframe=?", (tf,)).fetchone()[0] for tf in ("M1","M5","M15","M30","H1","H4","D1")}
        detail["duplicates"] = conn.execute("SELECT count(*) FROM (SELECT symbol,timeframe,open_time,count(*) n FROM bars GROUP BY 1,2,3 HAVING n>1)").fetchone()[0]
        detail["invalid_ohlc"] = conn.execute("SELECT count(*) FROM bars WHERE low>min(open,close) OR high<max(open,close) OR low<=0").fetchone()[0]
    conn.close()
    ok = quick == "ok" and integrity == "ok" and not fk and not missing and not detail.get("duplicates", 0) and not detail.get("invalid_ohlc", 0)
    if kind == "source":
        ok = ok and all(detail["timeframe_counts"].values())
    detail["passed"] = ok
    if not ok:
        raise SystemExit(json.dumps(detail, indent=2))
    return detail


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--db",type=Path,required=True); ap.add_argument("--kind",choices=("source","group6"),required=True); ap.add_argument("--report",type=Path)
    a=ap.parse_args(); result=verify(a.db,a.kind); text=json.dumps(result,indent=2,sort_keys=True); print(text)
    if a.report: a.report.parent.mkdir(parents=True,exist_ok=True); a.report.write_text(text+"\n",encoding="utf-8")
if __name__=="__main__": main()
