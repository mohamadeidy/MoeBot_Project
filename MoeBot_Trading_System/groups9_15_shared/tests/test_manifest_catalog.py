#!/usr/bin/env python3
from __future__ import annotations
import json,sqlite3,tempfile,unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from manifest_catalog import init,ingest

class CatalogTests(unittest.TestCase):
    def test_catalog_indexes_metadata_without_shard_files(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);m=td/"release.json"
            m.write_text(json.dumps({"status":"PASS","year":2023,"stage":7,"release_hash":"r"*64,"shards":[
              {"ordinal":0,"spec":{"family":"range_chain","year":2023,"symbol":"XAUUSD_","timeframe":"M15","root_month":"2023-01","bucket_count":4,"bucket_index":0},
               "archive_path":"missing-but-not-opened.zst","compressed_sha256":"c"*64,"compressed_size_bytes":123,
               "manifest_hash":"m"*64,"table_row_counts":{"school_interpretation":10,"evidence_chain":20},
               "table_logical_sha256":{"school_interpretation":"a"*64,"evidence_chain":"b"*64}}
            ]}))
            con=sqlite3.connect(td/"cat.sqlite");init(con);ingest(con,m,8)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM shard_catalog").fetchone()[0],1)
            self.assertEqual(con.execute("SELECT SUM(row_count) FROM shard_table_catalog").fetchone()[0],30)
            con.close()
if __name__=="__main__":unittest.main(verbosity=2)
