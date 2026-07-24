#!/usr/bin/env python3
"""Compare v2 and corrected-v3 annual runtime outputs without conflating operational byte hashes with research semantics.

Acceptance is strict in two dimensions:
1. Groups 2-5 stable research IDs and semantic payloads must remain identical, so published Group 6/7 upstream references stay resolvable.
2. Group 6 research-table semantic projections must be identical as multisets, while Group 6 internally generated IDs/record hashes that can incorporate dependency-byte identity are excluded from the semantic projection.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

G25_RULES: dict[str, dict[str, dict[str, Any]]] = {
    "group2": {
        "regime_states": {"id": "state_id", "exclude": ["state_pk","source_pk","config_pk","created_at_utc"]},
        "mtf_contexts": {"id": None, "exclude": ["state_pk","parent_state_pk","created_at_utc"]},
    },
    "group3": {
        "swings": {"id": "swing_id", "exclude": ["dataset_id","config_id"]},
        "break_events": {"id": "event_id", "exclude": ["dataset_id","config_id"]},
        "structure_states": {"id": "state_id", "exclude": ["dataset_id","config_id"]},
    },
    "group4": {
        "zones": {"id": "zone_id", "exclude": ["dataset_id","config_id"]},
        "zone_interactions": {"id": "interaction_id", "exclude": []},
        "zone_transitions": {"id": "transition_id", "exclude": []},
    },
    "group5": {
        "liquidity_pools": {"id": "pool_id", "exclude": ["dataset_id","config_id"]},
        "liquidity_events": {"id": "event_id", "exclude": []},
        "draw_states": {"id": "draw_id", "exclude": []},
        "inducements": {"id": "inducement_id", "exclude": []},
        "liquidity_voids": {"id": "void_id", "exclude": []},
        "pool_members": {"id": None, "exclude": []},
        "post_event_observations": {"id": "observation_id", "exclude": []},
        "void_observations": {"id": "observation_id", "exclude": []},
    },
}

G6_EXCLUDES: dict[str, list[str]] = {
    "displacement_legs": ["leg_id","feature_hash","record_hash"],
    "displacement_validation_events": ["validation_id","leg_id","fvg_id","record_hash"],
    "fvg_events": ["fvg_id","associated_leg_id","feature_hash","record_hash"],
    "fvg_lifecycle_summary": ["fvg_id","record_hash"],
    "fvg_state_transitions": ["transition_id","fvg_id","record_hash"],
    "fvg_visit_observations": ["visit_id","fvg_id","record_hash"],
    "fvg_visit_reactions": ["reaction_id","visit_id","fvg_id","record_hash"],
    "group6_evidence": ["evidence_id","subject_id","record_hash"],
    "imbalance_variants": ["variant_id","record_hash"],
    "inversion_fvg_relations": ["inversion_id","original_fvg_id","record_hash"],
    "inversion_retest_observations": ["observation_id","inversion_id","original_fvg_id","record_hash"],
    "liquidity_voids": ["void_id","record_hash"],
    "liquidity_void_members": ["void_id","member_id","record_hash"],
    "liquidity_void_state_transitions": ["transition_id","void_id","record_hash"],
    "liquidity_void_lifecycle_summary": ["void_id","record_hash"],
    "bpr_relations": ["bpr_id","bullish_fvg_id","bearish_fvg_id","record_hash"],
    "bpr_state_transitions": ["transition_id","bpr_id","record_hash"],
    "bpr_lifecycle_summary": ["bpr_id","record_hash"],
    "mtf_imbalance_relations": ["relation_id","child_id","parent_id","record_hash"],
}


def canonical(v: Any) -> str:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(v: Any) -> str:
    return hashlib.sha256(canonical(v).encode()).hexdigest()


def connect(path: Path) -> sqlite3.Connection:
    con=sqlite3.connect(f"file:{path.resolve()}?mode=ro",uri=True)
    con.row_factory=sqlite3.Row
    return con


def table_columns(con: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in con.execute(f'PRAGMA table_info("{table}")')]


def projection_counter(con: sqlite3.Connection, table: str, exclude: list[str]) -> tuple[list[str], Counter[str]]:
    cols=[c for c in table_columns(con,table) if c not in set(exclude)]
    if not cols:
        raise RuntimeError(f"no semantic columns remain for {table}")
    quoted=",".join(f'"{c}"' for c in cols)
    counter: Counter[str]=Counter()
    for row in con.execute(f'SELECT {quoted} FROM "{table}"'):
        counter[canonical([row[c] for c in cols])]+=1
    return cols,counter


def stable_ids(con: sqlite3.Connection, table: str, id_col: str | None) -> list[str] | None:
    if id_col is None:
        return None
    return [str(r[0]) for r in con.execute(f'SELECT "{id_col}" FROM "{table}" ORDER BY "{id_col}"')]


def compare_table(a: sqlite3.Connection,b: sqlite3.Connection,table: str,exclude: list[str],id_col: str|None=None) -> dict[str,Any]:
    ac=table_columns(a,table); bc=table_columns(b,table)
    schema_equal=ac==bc
    a_ids=stable_ids(a,table,id_col); b_ids=stable_ids(b,table,id_col)
    ids_equal=(a_ids==b_ids) if id_col else True
    cols_a,ca=projection_counter(a,table,exclude)
    cols_b,cb=projection_counter(b,table,exclude)
    projection_columns_equal=cols_a==cols_b
    semantic_equal=projection_columns_equal and ca==cb
    only_a=list((ca-cb).items())[:3]
    only_b=list((cb-ca).items())[:3]
    return {
      "schema_columns_equal":schema_equal,
      "stable_id_column":id_col,
      "stable_ids_equal":ids_equal,
      "stable_id_count_v2":len(a_ids) if a_ids is not None else None,
      "stable_id_count_v3":len(b_ids) if b_ids is not None else None,
      "semantic_columns":cols_a,
      "semantic_row_count_v2":sum(ca.values()),
      "semantic_row_count_v3":sum(cb.values()),
      "semantic_multiset_digest_v2":digest(sorted(ca.items())),
      "semantic_multiset_digest_v3":digest(sorted(cb.items())),
      "semantic_equal":semantic_equal,
      "sample_only_v2":only_a,
      "sample_only_v3":only_b,
      "pass":schema_equal and ids_equal and semantic_equal,
    }


def db_from_report(report: dict[str,Any],group: str) -> Path:
    return Path(report["artifacts"][group]["path"])


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--v2-report',type=Path,required=True)
    ap.add_argument('--v3-report',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    r2=json.loads(args.v2_report.read_text()); r3=json.loads(args.v3_report.read_text())
    if r2.get('year')!=r3.get('year'): raise RuntimeError('year mismatch')
    failures=[]; groups={}
    for group,rules in G25_RULES.items():
        a=connect(db_from_report(r2,group)); b=connect(db_from_report(r3,group)); tr={}
        for table,rule in rules.items():
            row=compare_table(a,b,table,list(rule['exclude']),rule['id'])
            tr[table]=row
            if not row['pass']: failures.append(f'{group}:{table}')
        a.close(); b.close(); groups[group]={'tables':tr,'pass':all(x['pass'] for x in tr.values())}
    a=connect(db_from_report(r2,'group6')); b=connect(db_from_report(r3,'group6')); tr={}
    for table,exclude in G6_EXCLUDES.items():
        row=compare_table(a,b,table,exclude,None)
        tr[table]=row
        if not row['semantic_equal'] or not row['schema_columns_equal']:
            failures.append(f'group6:{table}')
    # Group6 upstream reference compatibility: source IDs from G2/G3/G5 kept in semantic projections above.
    a.close(); b.close(); groups['group6']={'tables':tr,'pass':all(x['semantic_equal'] and x['schema_columns_equal'] for x in tr.values())}
    report={'format_version':1,'year':r2['year'],'method':'v2-v3 direct annual output comparison; Groups2-5 require exact stable research IDs plus semantic multiset equality; Group6 requires semantic multiset equality with dependency-byte-derived internal IDs/hashes excluded','groups':groups,'failures':failures,'status':'PASS' if not failures else 'FAIL'}
    report['report_hash']=digest(report)
    args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'status':report['status'],'year':report['year'],'failures':failures,'report_hash':report['report_hash']},indent=2))
    return 0 if not failures else 1

if __name__=='__main__': raise SystemExit(main())
