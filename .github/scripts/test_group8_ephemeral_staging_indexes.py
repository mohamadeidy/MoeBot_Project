#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("g8idx", HERE / "group8_ephemeral_staging_indexes.py")
assert SPEC and SPEC.loader
idx = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(idx)


class StagingIndexTests(unittest.TestCase):
    def test_indexes_preserve_all_rows_and_values(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = root / "staging.sqlite"
            con = sqlite3.connect(db)
            con.execute("CREATE TABLE stage_manifest(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
            for k,v in {"engine_version":"0.8.0","schema_version":"8.0.0","config_id":"cfg","logical_dependency_lineage_id":"lineage"}.items():
                con.execute("INSERT INTO stage_manifest VALUES(?,?)",(k,v))
            for _,table,columns in idx.INDEX_SPECS:
                if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():
                    continue
                defs=[]
                for c in columns:
                    typ="INTEGER" if c.endswith("time") or c in {"id","close_time","resolved_time","availability_time","available_at","expires_at","interaction_time","transition_time","transition_ordinal"} else "TEXT"
                    defs.append(f'"{c}" {typ}')
                con.execute(f'CREATE TABLE "{table}" ({", ".join(defs)})')
                vals=[]
                for c in columns:
                    vals.append(100 if c.endswith("time") or c in {"id","close_time","resolved_time","availability_time","available_at","expires_at","interaction_time","transition_time","transition_ordinal"} else "x")
                con.execute(f'INSERT INTO "{table}" VALUES({",".join("?" for _ in columns)})',vals)
            con.commit()
            before={t:[tuple(r) for r in con.execute(f'SELECT * FROM "{t}" ORDER BY rowid')] for _,t,_ in idx.INDEX_SPECS}
            con.close()
            report=root/"report.json";argv=sys.argv
            try:
                sys.argv=["x","--database",str(db),"--year","2023","--phase","fixture","--output",str(report)]
                self.assertEqual(idx.main(),0)
            finally:
                sys.argv=argv
            con=sqlite3.connect(db)
            after={t:[tuple(r) for r in con.execute(f'SELECT * FROM "{t}" ORDER BY rowid')] for _,t,_ in idx.INDEX_SPECS}
            index_names={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'ix_g8_exec_%'")}
            con.close()
            self.assertEqual(before,after)
            self.assertEqual(index_names,{name for name,_,_ in idx.INDEX_SPECS})
            r=json.loads(report.read_text())
            self.assertEqual(r["status"],"PASS")
            self.assertEqual(r["data_changes"],0)
            self.assertEqual(r["index_count"],len(idx.INDEX_SPECS))
            self.assertEqual(r["quick_check"],"ok")
            self.assertEqual(r["integrity_check"],"ok")
            self.assertEqual(r["foreign_key_errors"],0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
