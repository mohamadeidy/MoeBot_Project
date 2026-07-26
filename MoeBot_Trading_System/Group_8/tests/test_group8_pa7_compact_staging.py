#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from group8_pa7_shard_executor import CHAIN_DEFINITIONS, PA7_REQUIRED_TABLES, ShardSpec, run_shard
from test_group8_engine_v0_8_0 import ART, make_stage


def make_compact(full: Path, compact: Path) -> None:
    src=sqlite3.connect(full);dst=sqlite3.connect(compact)
    try:
        for table in ('stage_manifest','staging_metadata'):
            schema=src.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()[0];dst.execute(schema)
            rows=src.execute(f'SELECT * FROM "{table}"').fetchall();n=len(src.execute(f'PRAGMA table_info("{table}")').fetchall());dst.executemany(f'INSERT INTO "{table}" VALUES ({",".join("?" for _ in range(n))})',rows)
        for group,names in PA7_REQUIRED_TABLES.items():
            for name in names:
                table=f'{group}__{name}';schema=src.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()[0];dst.execute(schema)
                rows=src.execute(f'SELECT * FROM "{table}"').fetchall();n=len(src.execute(f'PRAGMA table_info("{table}")').fetchall());dst.executemany(f'INSERT INTO "{table}" VALUES ({",".join("?" for _ in range(n))})',rows)
        dst.execute("INSERT OR REPLACE INTO stage_manifest(key,value) VALUES('materialization_scope','PA7_COMPACT_V1')")
        dst.execute("INSERT OR REPLACE INTO stage_manifest(key,value) VALUES('materialized_groups_json',?)",(json.dumps(list(PA7_REQUIRED_TABLES),separators=(',',':')),));dst.commit()
    finally:src.close();dst.close()


def cmap(db:Path)->dict[str,str]:
    con=sqlite3.connect(db)
    try:
        q=','.join('?' for _ in CHAIN_DEFINITIONS);return {r[0]:r[1] for r in con.execute(f'SELECT candidate_id,candidate_hash FROM price_action_pattern_candidate WHERE definition_id IN ({q})',CHAIN_DEFINITIONS)}
    finally:con.close()


class CompactPA7StagingTest(unittest.TestCase):
    def test_compact_and_full_staging_emit_identical_shard(self)->None:
        with tempfile.TemporaryDirectory() as td:
            t=Path(td);full=t/'full.sqlite';compact=t/'compact.sqlite';make_stage(full);make_compact(full,compact);spec=ShardSpec(2023,'XAUUSD_','M15',None,4,0)
            full_out=t/'full-out.sqlite';compact_out=t/'compact-out.sqlite'
            run_shard(staging_db=full,work_db=t/'fw.sqlite',output_db=full_out,artifacts_root=ART,spec=spec,manifest_path=t/'fm.json')
            run_shard(staging_db=compact,work_db=t/'cw.sqlite',output_db=compact_out,artifacts_root=ART,spec=spec,manifest_path=t/'cm.json')
            self.assertEqual(cmap(full_out),cmap(compact_out));self.assertGreater(len(cmap(compact_out)),0)
            con=sqlite3.connect(compact)
            try:
                tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")};self.assertNotIn('group2__regime_states',tables);self.assertNotIn('group3__structure_states',tables);self.assertIn('group6__fvg_events',tables)
            finally:con.close()

if __name__=='__main__':unittest.main()
