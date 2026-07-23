#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from moebot_group7_engine import DEFINITIONS


def bars_around(con: sqlite3.Connection, timeframe: str, anchor: int, before: int = 14, after: int = 14) -> List[sqlite3.Row]:
    left = list(con.execute(
        "SELECT id,open,high,low,close,close_time FROM bars WHERE timeframe=? AND close_time<=? ORDER BY close_time DESC,id DESC LIMIT ?",
        (timeframe, anchor, before),
    )); left.reverse()
    right = list(con.execute(
        "SELECT id,open,high,low,close,close_time FROM bars WHERE timeframe=? AND close_time>? ORDER BY close_time,id LIMIT ?",
        (timeframe, anchor, after),
    ))
    return left + right


def plot(rows: List[sqlite3.Row], zone: Optional[Dict[str, Any]], title: str, outfile: Path, anchors: List[Tuple[int, str]]) -> None:
    if not rows:
        raise ValueError(f"No bars for {title}")
    fig, ax = plt.subplots(figsize=(12, 5.2))
    high = max(r[2] for r in rows); low = min(r[3] for r in rows); span = max(high-low, 1e-9)
    time_to_x = {}
    for x, row in enumerate(rows):
        bid, o, h, l, c, ct = row
        time_to_x[ct] = x
        ax.vlines(x, l, h, linewidth=1)
        bottom = min(o, c); height = max(abs(c-o), span*0.001)
        ax.add_patch(Rectangle((x-0.32, bottom), 0.64, height, fill=(c >= o), alpha=0.55))
    if zone:
        ax.axhspan(zone["lower"], zone["upper"], alpha=0.18)
        ax.axhline(zone["lower"], linewidth=0.8); ax.axhline(zone["upper"], linewidth=0.8)
        ax.text(0.01, 0.98, f"{zone['definition_id']} [{zone['lower']:.8f}, {zone['upper']:.8f}]", transform=ax.transAxes, va="top")
    for ts, label in anchors:
        nearest = min(range(len(rows)), key=lambda i: abs(rows[i][5]-ts))
        ax.annotate(label, (nearest, rows[nearest][2]), xytext=(nearest, rows[nearest][2] + span*0.08), arrowprops={"arrowstyle":"->"}, fontsize=8)
    tick_step = max(1, len(rows)//8)
    ax.set_xticks(range(0, len(rows), tick_step))
    ax.set_xticklabels([str(rows[i][5]) for i in range(0, len(rows), tick_step)], rotation=30, ha="right", fontsize=8)
    ax.set_title(title); ax.set_xlabel("Closed-bar time"); ax.set_ylabel("Price"); ax.grid(True, alpha=0.2)
    fig.tight_layout(); fig.savefig(outfile, dpi=150); plt.close(fig)


def run(source: Path, group6: Path, group7: Path, outdir: Path) -> Dict[str, Any]:
    outdir.mkdir(parents=True, exist_ok=True)
    cs = sqlite3.connect(f"file:{source}?mode=ro", uri=True); cs.row_factory = sqlite3.Row
    cg6 = sqlite3.connect(f"file:{group6}?mode=ro", uri=True); cg6.row_factory = sqlite3.Row
    cg7 = sqlite3.connect(f"file:{group7}?mode=ro", uri=True); cg7.row_factory = sqlite3.Row
    cases: List[Dict[str, Any]] = []

    # One mechanically selected accepted case per definition; lifecycle variety is
    # preferred, never future return or profitability.
    for definition in DEFINITIONS:
        row = cg7.execute("""
            SELECT z.*,s.status,s.freshness,s.first_touch_time,s.invalidated_time,s.visit_count,s.mitigation_count
            FROM institutional_zones z JOIN zone_lifecycle_summary s USING(zone_id)
            WHERE z.definition_id=?
            ORDER BY (s.first_touch_time IS NOT NULL) DESC,(s.invalidated_time IS NOT NULL) DESC,z.availability_time,z.zone_id LIMIT 1
        """, (definition,)).fetchone()
        if not row:
            continue
        z = dict(row); anchor = z["first_touch_time"] or z["invalidated_time"] or z["availability_time"]
        anchors = [(z["availability_time"], "available")]
        if z["first_touch_time"]: anchors.append((z["first_touch_time"], "first touch"))
        if z["invalidated_time"]: anchors.append((z["invalidated_time"], "invalidated"))
        filename = f"accepted_{definition}.png"
        plot(bars_around(cs,z["timeframe"],anchor),z,f"Accepted {definition} — rule-selected",outdir/filename,anchors)
        cases.append({"type":"accepted","definition":definition,"image":filename,"zone_id":z["zone_id"],"selection":"earliest with lifecycle variety"})

    # Failed candidates are first failures by definition and leg availability.
    for definition in [d for d,spec in DEFINITIONS.items() if not spec["derived"]]:
        ev = cg7.execute("SELECT * FROM block_evaluations WHERE definition_id=? AND passed=0 AND source_leg_id IS NOT NULL ORDER BY evaluation_time,evaluation_id LIMIT 1",(definition,)).fetchone()
        if not ev: continue
        leg = cg6.execute("SELECT timeframe,availability_time,origin_window_start,origin_window_end FROM displacement_legs WHERE leg_id=?",(ev["source_leg_id"],)).fetchone()
        if not leg: continue
        filename=f"failed_{definition}.png"
        plot(bars_around(cs,leg["timeframe"],leg["availability_time"]),None,f"Failed {definition} — reasons preserved",outdir/filename,[(leg["availability_time"],"evaluation available")])
        cases.append({"type":"failed","definition":definition,"image":filename,"evaluation_id":ev["evaluation_id"],"reasons":json.loads(ev["reasons_json"])})

    boundary = cg7.execute("""
        SELECT z.*,t.transition_time FROM zone_state_transitions t JOIN institutional_zones z USING(zone_id)
        WHERE t.event_type='first_touch' AND NOT EXISTS(
          SELECT 1 FROM zone_state_transitions x WHERE x.zone_id=t.zone_id AND x.event_type='invalidated' AND x.transition_time=t.transition_time)
        ORDER BY t.transition_time,t.transition_id LIMIT 1
    """).fetchone()
    if boundary:
        z=dict(boundary); filename="boundary_touch_not_invalidation.png"
        plot(bars_around(cs,z["timeframe"],z["transition_time"]),z,"Boundary — touch/edge overlap is not close-through",outdir/filename,[(z["transition_time"],"touch, not invalidation")])
        cases.append({"type":"boundary","image":filename,"zone_id":z["zone_id"]})

    two = cg7.execute("""
        SELECT z.*,c.transition_time candidate_time,i.transition_time invalidated_time
        FROM institutional_zones z
        JOIN zone_state_transitions c ON c.zone_id=z.zone_id AND c.event_type='invalidation_candidate'
        JOIN zone_state_transitions i ON i.zone_id=z.zone_id AND i.event_type='invalidated' AND i.transition_time>c.transition_time
        WHERE z.definition_id IN ('loose_order_block','supply_demand_origin')
        ORDER BY c.transition_time,z.zone_id LIMIT 1
    """).fetchone()
    if two:
        z=dict(two); filename="two_close_invalidation.png"
        plot(bars_around(cs,z["timeframe"],z["invalidated_time"]),z,"Two-close invalidation — candidate and final are distinct",outdir/filename,[(z["candidate_time"],"candidate"),(z["invalidated_time"],"final")])
        cases.append({"type":"lifecycle","image":filename,"zone_id":z["zone_id"]})

    cg7.close(); cg6.close(); cs.close()
    sections=[]
    for idx,case in enumerate(cases,1):
        sections.append(f"<section><h2>{idx}. {html.escape(case['type']+' '+case.get('definition',''))}</h2><img src='{html.escape(case['image'])}'><pre>{html.escape(json.dumps(case,indent=2))}</pre></section>")
    page="""<!doctype html><html><head><meta charset='utf-8'><title>Group 7 Real Visual Audit</title><style>body{font-family:Arial;max-width:1250px;margin:auto;padding:24px}img{width:100%;border:1px solid #bbb}section{margin-bottom:38px}pre{white-space:pre-wrap;background:#f5f5f5;padding:12px}</style></head><body><h1>MoeBot Group 7 — Real-data Visual Audit</h1><p>Rule-selected accepted, failed, boundary, and lifecycle cases. Selection never uses PnL, MFE, MAE, or future return.</p>"""+"".join(sections)+"</body></html>"
    (outdir/"VISUAL_AUDIT_REAL.html").write_text(page,encoding="utf-8")
    result={"passed":len(cases)>0,"cases":len(cases),"case_records":cases,"html":"VISUAL_AUDIT_REAL.html"}
    (outdir/"VISUAL_AUDIT_REAL.json").write_text(json.dumps(result,indent=2,sort_keys=True),encoding="utf-8")
    return result


def main() -> None:
    p=argparse.ArgumentParser(); p.add_argument("--source",required=True); p.add_argument("--group6",required=True); p.add_argument("--group7",required=True); p.add_argument("--outdir",required=True)
    a=p.parse_args(); print(json.dumps(run(Path(a.source),Path(a.group6),Path(a.group7),Path(a.outdir)),indent=2,sort_keys=True))

if __name__=="__main__": main()
