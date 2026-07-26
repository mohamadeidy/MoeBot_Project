#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

from group8_engine_core import BarFeature, build_bar_features, canonical_hash, canonical_json, deterministic_id, open_rw, sha256_file
from group8_engine_model import ENGINE_VERSION, SCHEMA_VERSION, SCHOOLS, PATTERN_KINDS, attach_ro, q
from group8_engine_stages_price_action import Group8PriceActionStages
from group8_engine_stages_schools import Group8SchoolStages
from group8_engine_finalize import Group8FinalizeStages

class Group8Engine(Group8PriceActionStages, Group8SchoolStages, Group8FinalizeStages):

    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.root = args.group8_root
        self.config = json.loads((self.root / "FROZEN_CONFIG.json").read_text())
        self.definitions_doc = json.loads((self.root / "01_DEFINITION_REGISTRY.json").read_text())
        self.definitions = self.definitions_doc["definitions"]
        self.adapter_map = json.loads((self.root / "UPSTREAM_ADAPTER_MAP.json").read_text())
        self.bindings = json.loads((self.root / "UPSTREAM_VALUE_BINDINGS.json").read_text())
        self.annual_registry = json.loads((self.root / "UPSTREAM_ANNUAL_DEPENDENCY_REGISTRY.json").read_text())
        self.contract = json.loads((self.root / "contracts/UPSTREAM_INPUT_CONTRACT.json").read_text())
        self.schema_sql = (self.root / "02_SCHEMA.sql").read_text()
        self.output = args.output
        self.year = int(args.year)
        self.reg_year = self.annual_registry["years"][str(self.year)]
        self.con = open_rw(self.output)
        self._attach_all()
        self.dataset_id = self._dataset_id()
        self.dataset_start, self.dataset_end, self.symbol = self._dataset_bounds()
        self.price_increment: float | None = None
        self.bar_by_id: dict[int, BarFeature] = {}
        self.timeframe_bars: dict[str, list[BarFeature]] = {}
        self.boundaries: dict[str, list[Boundary]] = defaultdict(list)
        self.range_contexts: list[dict[str, Any]] = []

    def _attach_all(self) -> None:
        attach_ro(self.con, "src", self.args.source_db)
        for group in range(2, 8):
            attach_ro(self.con, f"g{group}", getattr(self.args, f"group{group}_db"))

    def _dataset_id(self) -> str:
        payload = {
            "year": self.year,
            "lineage": self.annual_registry["lineage"],
            "registry_hash": self.annual_registry["registry_hash"],
            "config_id": self.config["config_id"],
        }
        return deterministic_id("g8ds", payload)

    def _dataset_bounds(self) -> tuple[int, int, str]:
        row = self.con.execute("SELECT MIN(available_at),MAX(available_at),MIN(symbol) FROM src.bars").fetchone()
        if row is None or row[0] is None:
            raise RuntimeError("source bars are empty")
        return int(row[0]), int(row[1]), str(row[2])

    def initialize(self) -> None:
        self.con.executescript(self.schema_sql)
        self._register_static()
        self._build_temp_bar_features()
        self.price_increment = self._resolve_price_increment()
        self._audit("engine_initialize", "PASS", {"dataset_id": self.dataset_id, "price_increment": self.price_increment})
        self.con.commit()

    def _register_static(self) -> None:
        config_json = canonical_json(self.config)
        self.con.execute(
            "INSERT OR IGNORE INTO config_registry(config_id,engine_version,schema_version,config_json,config_hash,created_at) VALUES(?,?,?,?,?,?)",
            (self.config["config_id"], ENGINE_VERSION, SCHEMA_VERSION, config_json, canonical_hash(self.config), self.dataset_start),
        )
        g7db = self.reg_year["group7_verification"]["database"]
        src = self.annual_registry["source_databases"][str(self.year)]
        ds_payload = {
            "dataset_id": self.dataset_id, "symbol": self.symbol, "year": self.year,
            "lineage": self.annual_registry["lineage"], "logical_dependency_lineage_id": self.annual_registry["logical_lineage_id"],
            "source": src, "group7": g7db, "config_id": self.config["config_id"],
        }
        ds_hash = canonical_hash(ds_payload)
        self.con.execute(
            "INSERT OR IGNORE INTO dataset_registry(dataset_id,symbol,year,lineage,logical_dependency_lineage_id,dependency_release_anchor_tag,source_db_filename,source_db_size_bytes,source_db_sha256,group7_db_filename,group7_db_size_bytes,group7_db_sha256,group7_logic_source_closure_tag,group7_logic_source_closure_commit_sha,coherent_lineage_amendment_hash,annual_dependency_registry_hash,adapter_map_hash,categorical_dictionary_hash,value_bindings_hash,definition_registry_hash,created_at,record_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (self.dataset_id, self.symbol, self.year, self.annual_registry["lineage"], self.annual_registry["logical_lineage_id"],
             self.annual_registry["release_anchor_tag"], src["database_filename"], src["database_size_bytes"], src["database_sha256"],
             g7db["filename"], g7db["size_bytes"], g7db["sha256"], self.config["group7_logic_source"]["closure_tag"],
             self.config["group7_logic_source"]["closure_commit_sha"], self.config["coherent_lineage_amendment_hash"],
             self.config["annual_dependency_registry_hash"], self.config["adapter_map_hash"], self.config["categorical_dictionary_hash"],
             self.config["value_binding_hash"], self.definitions_doc["registry_hash"], self.dataset_start, ds_hash),
        )
        manifest = self.reg_year["manifest"]
        for group, rec in sorted(manifest["packages"].items()):
            dep_payload = {"group": group, "database_filename": rec["database_filename"], "size": rec["database_size_bytes"], "sha256": rec["database_sha256"], "lineage": manifest["lineage"]}
            dep_id = deterministic_id("g8dep", dep_payload)
            engine_version = {"group2":"0.2.1","group3":"0.1.1","group4":"0.1.6","group5":"0.1.6","group6":"0.6.4","group7":"0.7.5"}[group]
            schema_version = {"group2":"2.1.0","group3":"3.0.0","group4":"4.5.0","group5":"5.1.0","group6":"6.35.0","group7":"7.5.0"}[group]
            adapter_group = self.adapter_map["adapters"][group]
            adapter_hash = canonical_hash({k:v["adapter_hash"] for k,v in sorted(adapter_group.items())})
            self.con.execute(
                "INSERT OR IGNORE INTO dependency_registry(dependency_id,group_name,engine_version,schema_version,config_id,filename,size_bytes,sha256,lineage,read_only,transitive,source_dependency_id,adapter_hash,record_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (dep_id, group, engine_version, schema_version, None, rec["database_filename"], rec["database_size_bytes"], rec["database_sha256"], manifest["lineage"], 1, 0, None, adapter_hash, canonical_hash(dep_payload)),
            )
        for school_id,(version,name) in SCHOOLS.items():
            scope={"definitions":[k for k,v in self.definitions.items() if v["school"]==school_id]}
            prohibitions={"trading_outputs":True,"preferred_school":False,"profitability":False}
            payload={"school_id":school_id,"school_version":version,"school_name":name,"scope":scope,"prohibitions":prohibitions}
            self.con.execute("INSERT OR IGNORE INTO school_registry(school_id,school_version,school_name,scope_json,prohibitions_json,school_hash) VALUES(?,?,?,?,?,?)",
                             (school_id,version,name,canonical_json(scope),canonical_json(prohibitions),canonical_hash(payload)))
        for definition_id, definition in sorted(self.definitions.items()):
            djson=canonical_json(definition); dh=canonical_hash(definition); school=definition["school"]; kind=definition["kind"]
            if kind in PATTERN_KINDS:
                self.con.execute("INSERT OR IGNORE INTO pattern_definition_registry(definition_id,definition_version,school_id,definition_kind,definition_json,definition_hash) VALUES(?,?,?,?,?,?)",
                                 (definition_id,definition["version"],school,kind,djson,dh))
            else:
                self.con.execute("INSERT OR IGNORE INTO interpretation_definition_registry(definition_id,definition_version,school_id,interpretation_kind,definition_json,definition_hash) VALUES(?,?,?,?,?,?)",
                                 (definition_id,definition["version"],school,kind,djson,dh))
        meta={
            "engine_version":ENGINE_VERSION,"schema_version":SCHEMA_VERSION,"config_id":self.config["config_id"],"dataset_id":self.dataset_id,
            "definition_registry_hash":self.definitions_doc["registry_hash"],"adapter_map_hash":self.config["adapter_map_hash"],
            "annual_dependency_registry_hash":self.config["annual_dependency_registry_hash"],"lineage":self.annual_registry["lineage"],
        }
        self.con.executemany("INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)",[(k,str(v)) for k,v in sorted(meta.items())])

    def _build_temp_bar_features(self) -> None:
        self.con.executescript("""
        DROP TABLE IF EXISTS temp.tmp_bar_features;
        CREATE TEMP TABLE tmp_bar_features(
          bar_id INTEGER PRIMARY KEY,symbol TEXT NOT NULL,timeframe TEXT NOT NULL,open_time INTEGER NOT NULL,close_time INTEGER NOT NULL,available_at INTEGER NOT NULL,
          open REAL NOT NULL,high REAL NOT NULL,low REAL NOT NULL,close REAL NOT NULL,prev_bar_id INTEGER,prev_close REAL,
          full_range REAL NOT NULL,body REAL NOT NULL,body_lower REAL NOT NULL,body_upper REAL NOT NULL,upper_wick REAL NOT NULL,lower_wick REAL NOT NULL,
          body_to_range REAL,upper_wick_to_range REAL,lower_wick_to_range REAL,open_location REAL,close_location REAL,true_range REAL NOT NULL,atr REAL,
          range_to_atr REAL,body_to_atr REAL,overlap_with_previous REAL,direction TEXT NOT NULL,content_hash TEXT NOT NULL
        );
        CREATE INDEX tmp_idx_bar_tf_time ON tmp_bar_features(timeframe,available_at);
        CREATE INDEX tmp_idx_bar_tf_close ON tmp_bar_features(timeframe,close_time);
        """)
        timeframes=[r[0] for r in self.con.execute("SELECT DISTINCT timeframe FROM src.bars ORDER BY timeframe")]
        insert_sql="INSERT INTO tmp_bar_features VALUES("+",".join("?" for _ in range(30))+")"
        for tf in timeframes:
            rows=[dict(r) for r in self.con.execute("SELECT id,symbol,timeframe,open_time,close_time,available_at,open,high,low,close,content_hash FROM src.bars WHERE timeframe=? ORDER BY open_time,id",(tf,))]
            feats=build_bar_features(rows,int(self.config["feature_parameters"]["atr_period"]))
            self.timeframe_bars[tf]=feats
            vals=[]
            for f in feats:
                self.bar_by_id[f.bar_id]=f
                vals.append((f.bar_id,f.symbol,f.timeframe,f.open_time,f.close_time,f.available_at,f.open,f.high,f.low,f.close,f.prev_bar_id,f.prev_close,f.full_range,f.body,f.body_lower,f.body_upper,f.upper_wick,f.lower_wick,f.body_to_range,f.upper_wick_to_range,f.lower_wick_to_range,f.open_location,f.close_location,f.true_range,f.atr,f.range_to_atr,f.body_to_atr,f.overlap_with_previous,f.direction,f.content_hash))
            self.con.executemany(insert_sql,vals)
            self.con.commit()

    def _resolve_price_increment(self) -> float | None:
        tables={r[0] for r in self.con.execute("SELECT name FROM src.sqlite_master WHERE type='table'")}
        if "metadata" in tables:
            entries={str(r[0]).lower():str(r[1]) for r in self.con.execute("SELECT key,value FROM src.metadata")}
            for key in ("tick_size","point","symbol_point","price_increment"):
                if key in entries:
                    try:
                        val=float(entries[key])
                        if val>0 and math.isfinite(val):
                            self._audit("price_increment", "PASS", {"method":"metadata","key":key,"value":val})
                            return val
                    except Exception:
                        pass
            for key in ("digits","price_digits","symbol_digits"):
                if key in entries:
                    try:
                        digits=int(float(entries[key]));val=10.0**(-digits)
                        if 0<val<1:
                            self._audit("price_increment", "PASS", {"method":"metadata_digits","key":key,"digits":digits,"value":val})
                            return val
                    except Exception:
                        pass
        digits=int(self.config["feature_parameters"]["feature_round_digits"]); scale=10**digits;g=0;base=None
        for row in self.con.execute("SELECT open,high,low,close FROM src.bars ORDER BY id"):
            for v in row:
                iv=int(round(float(v)*scale))
                if base is None: base=iv
                else: g=math.gcd(g,abs(iv-base))
        if g>0:
            val=g/scale
            self._audit("price_increment", "PASS", {"method":"observed_decimal_lattice","round_digits":digits,"value":val})
            return val
        self._audit("price_increment", "WARN", {"method":"exact_stored_equality_fallback","value":None})
        return None

    def _audit(self, check_name: str, status: str, details: Mapping[str, Any], scope: str="engine") -> None:
        checked_at=self.dataset_end
        payload={"check_name":check_name,"status":status,"scope":scope,"details":details,"checked_at":checked_at}
        aid=deterministic_id("g8audit",payload); ah=canonical_hash(payload)
        self.con.execute("INSERT OR IGNORE INTO group8_audit_evidence(audit_id,check_name,status,scope,details_json,checked_at,audit_hash) VALUES(?,?,?,?,?,?,?)",
                         (aid,check_name,status,scope,canonical_json(details),checked_at,ah))

    def run(self) -> None:
        self.initialize()
        self.build_basic_price_action()
        self.build_dow()
        self.build_ranges_and_boundaries()
        self.build_breakouts_and_context_rejections()
        self.build_failed_breakouts_and_retests()
        self.build_structural_narratives()
        self.build_ict()
        self.build_wyckoff()
        self.build_cross_school_and_mtf()
        self.finalize()

def parse_args() -> argparse.Namespace:
    ap=argparse.ArgumentParser()
    ap.add_argument('--group8-root',type=Path,required=True)
    ap.add_argument('--year',choices=('2023','2024'),required=True)
    ap.add_argument('--source-db',type=Path,required=True)
    for group in range(2,8): ap.add_argument(f'--group{group}-db',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    return ap.parse_args()

def main()->int:
    args=parse_args();engine=Group8Engine(args);engine.run();print(json.dumps({'status':'PASS','output':str(args.output),'size_bytes':args.output.stat().st_size,'sha256':sha256_file(args.output)},indent=2));return 0

if __name__=="__main__": raise SystemExit(main())
