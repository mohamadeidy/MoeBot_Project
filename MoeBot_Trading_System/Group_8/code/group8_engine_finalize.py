#!/usr/bin/env python3
from __future__ import annotations
import json
import sqlite3
from group8_engine_core import canonical_hash, canonical_json, deterministic_id
from group8_engine_model import ENGINE_VERSION, PATTERN_KINDS, q

class Group8FinalizeStages:

    def finalize(self) -> None:
        # Initial lifecycle event for every hypothesis; completed/right-censored states append without mutating creation.
        for r in self.con.execute("SELECT hypothesis_id,initial_state,event_time,availability_time,upstream_refs_json FROM narrative_hypothesis ORDER BY availability_time,hypothesis_id"):
            payload={"hypothesis_id":r["hypothesis_id"],"ordinal":0,"state":r["initial_state"],"availability_time":int(r["availability_time"])};lid=deterministic_id("g8hl",payload);lh=canonical_hash(payload)
            self.con.execute("INSERT OR IGNORE INTO hypothesis_lifecycle_event(lifecycle_event_id,hypothesis_id,lifecycle_ordinal,source_type,source_id,event_time,availability_time,lifecycle_state,details_json,lifecycle_hash) VALUES(?,?,?,?,?,?,?,?,?,?)",
                             (lid,r["hypothesis_id"],0,"creation",r["hypothesis_id"],int(r["event_time"]),int(r["availability_time"]),r["initial_state"],canonical_json({"creation_immutable":True}),lh))
        for tf,bars in sorted(self.timeframe_bars.items()):
            if not bars: continue
            snap=canonical_hash({"dataset_id":self.dataset_id,"timeframe":tf,"last_bar_id":bars[-1].bar_id,"last_time":bars[-1].available_at,"engine_version":ENGINE_VERSION})
            self.con.execute("INSERT OR REPLACE INTO processing_checkpoint(symbol,timeframe,stage,status,last_bar_id,last_time,snapshot_hash,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                             (self.symbol,tf,"full_engine","complete",bars[-1].bar_id,bars[-1].available_at,snap,bars[-1].available_at))
        causal_checks={}
        for table,timepairs in {
            "price_action_pattern_candidate":("event_time","availability_time"),
            "school_interpretation":("event_time","availability_time"),
            "narrative_hypothesis":("event_time","availability_time"),
            "evidence_chain":("event_time","availability_time"),
            "multi_timeframe_context_relation":("event_time","availability_time"),
        }.items():
            n=self.con.execute(f"SELECT COUNT(*) FROM {table} WHERE {timepairs[1]}<{timepairs[0]}").fetchone()[0];causal_checks[table]=n
        coverage={}
        for did in sorted(self.definitions):
            kind=self.definitions[did]["kind"]
            table="price_action_pattern_candidate" if kind in PATTERN_KINDS else "narrative_hypothesis" if kind=="narrative_hypothesis" else "school_interpretation"
            coverage[did]=self.con.execute(f"SELECT COUNT(*) FROM {table} WHERE definition_id=?",(did,)).fetchone()[0]
        status="PASS" if all(v==0 for v in causal_checks.values()) else "FAIL"
        self._audit("causality",status,causal_checks,"final")
        self._audit("definition_coverage","PASS",coverage,"final")
        prohibited=["buy_signal","sell_signal","entry_price","stop_loss","take_profit","profit","pnl","mfe","mae","future_return","position_size","risk_reward"]
        schema='\n'.join(r[0] or '' for r in self.con.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL"));hits=[x for x in prohibited if x in schema.lower()]
        self._audit("prohibited_output_schema","PASS" if not hits else "FAIL",{"hits":hits},"final")
        self.con.commit()
        quick=self.con.execute("PRAGMA quick_check").fetchone()[0];integrity=self.con.execute("PRAGMA integrity_check").fetchone()[0];fk=len(self.con.execute("PRAGMA foreign_key_check").fetchall())
        self._audit("sqlite_integrity","PASS" if quick=="ok" and integrity=="ok" and fk==0 else "FAIL",{"quick_check":quick,"integrity_check":integrity,"foreign_key_errors":fk},"final")
        self.con.commit()
        self.con.execute("DROP TABLE IF EXISTS temp.tmp_bar_features")
        self.con.commit()
        for alias in ("src","g2","g3","g4","g5","g6","g7"):
            try:self.con.execute(f"DETACH DATABASE {q(alias)}")
            except sqlite3.Error:pass
        self.con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.con.execute("VACUUM")
        self.con.commit();self.con.close()
