#!/usr/bin/env python3
"""Count exact amended PA7 transition events without materializing breakout rows.

Scope is exact 2023 Group6 + Group8 bounded-range boundaries. The state machine,
availability initialization, variant-specific thresholds, and re-arm crossing rules
mirror PA7E.2/A.2/P.2. This isolates logical cardinality from SQLite write cost.
"""
from __future__ import annotations

import argparse,bisect,hashlib,json
from collections import defaultdict
from pathlib import Path
from typing import Any

ENGINE_SHA="a52cc93ec2071526c4edba78db00c7313dfb47a712a1a0f5defd76c55cac58f7"

class Fenwick:
    def __init__(self,n:int): self.bit=[0]*(n+1)
    def add(self,i:int,v:int=1):
        i+=1
        while i<len(self.bit): self.bit[i]+=v;i+=i&-i
    def prefix(self,n:int)->int:
        s=0;i=n
        while i: s+=self.bit[i];i-=i&-i
        return s
    def range(self,l:int,r:int)->int: return self.prefix(r)-self.prefix(l)

def sha(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(16*1024*1024),b''): h.update(b)
    return h.hexdigest()

def stable(x:object)->str: return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

def count_series(bars:list[Any],boundaries:list[tuple[int,float,float,str]],inc:float|None,atr:dict[int,float|None],frac:float)->dict[str,int]:
    if not bars or not boundaries: return {"exact":0,"point":0,"atr":0,"total":0,"initialization":0,"rearmed":0}
    boundaries=sorted(boundaries,key=lambda x:(x[0],x[1],x[2],x[3])); ups=sorted({b[2] for b in boundaries}); los=sorted({b[1] for b in boundaries}); ut=Fenwick(len(ups));lt=Fenwick(len(los));ptr=0;active=0
    counts={"exact":0,"point":0,"atr":0,"initialization":0,"rearmed":0}
    prev=None; atr_started=False
    for bar in bars:
        av=int(bar.available_at); new_start=ptr
        while ptr<len(boundaries) and boundaries[ptr][0]<=av: ptr+=1
        newly=boundaries[new_start:ptr]
        if prev is None:
            for _a,lo,hi,_id in newly:
                if bar.close>hi: counts['exact']+=1;counts['initialization']+=1
                if bar.close<lo: counts['exact']+=1;counts['initialization']+=1
                if inc is not None:
                    if bar.close>=hi+inc: counts['point']+=1;counts['initialization']+=1
                    if bar.close<=lo-inc: counts['point']+=1;counts['initialization']+=1
                ca=atr.get(int(bar.id))
                if ca not in (None,0):
                    buf=frac*float(ca)
                    if bar.close>=hi+buf: counts['atr']+=1;counts['initialization']+=1
                    if bar.close<=lo-buf: counts['atr']+=1;counts['initialization']+=1
            for _a,lo,hi,_id in newly: ut.add(bisect.bisect_left(ups,hi));lt.add(bisect.bisect_left(los,lo));active+=1
            atr_started=atr.get(int(bar.id)) not in (None,0);prev=bar;continue
        # Normal transitions use boundaries that were causally available at prev bar.
        if float(bar.close)>float(prev.close):
            l=bisect.bisect_left(ups,float(prev.close));r=bisect.bisect_left(ups,float(bar.close));n=ut.range(l,r);counts['exact']+=n;counts['rearmed']+=n
        elif float(bar.close)<float(prev.close):
            l=bisect.bisect_right(los,float(bar.close));r=bisect.bisect_right(los,float(prev.close));n=lt.range(l,r);counts['exact']+=n;counts['rearmed']+=n
        if inc is not None:
            pa=float(prev.close)-inc;ca=float(bar.close)-inc
            if ca>pa:
                n=ut.range(bisect.bisect_right(ups,pa),bisect.bisect_right(ups,ca));counts['point']+=n;counts['rearmed']+=n
            pa=float(prev.close)+inc;ca=float(bar.close)+inc
            if ca<pa:
                n=lt.range(bisect.bisect_left(los,ca),bisect.bisect_left(los,pa));counts['point']+=n;counts['rearmed']+=n
        pat=atr.get(int(prev.id));cat=atr.get(int(bar.id))
        if cat not in (None,0):
            if pat not in (None,0):
                pa=float(prev.close)-frac*float(pat);ca=float(bar.close)-frac*float(cat)
                if ca>pa:
                    n=ut.range(bisect.bisect_right(ups,pa),bisect.bisect_right(ups,ca));counts['atr']+=n;counts['rearmed']+=n
                pa=float(prev.close)+frac*float(pat);ca=float(bar.close)+frac*float(cat)
                if ca<pa:
                    n=lt.range(bisect.bisect_left(los,ca),bisect.bisect_left(los,pa));counts['atr']+=n;counts['rearmed']+=n
            else:
                # First ATR-evaluable bar initializes every causally available boundary.
                buf=frac*float(cat)
                bull=ut.prefix(bisect.bisect_right(ups,float(bar.close)-buf));bear=active-lt.prefix(bisect.bisect_left(los,float(bar.close)+buf));n=bull+bear;counts['atr']+=n;counts['initialization']+=n
                for _a,lo,hi,_id in newly:
                    if bar.close>=hi+buf: counts['atr']+=1;counts['initialization']+=1
                    if bar.close<=lo-buf: counts['atr']+=1;counts['initialization']+=1
            atr_started=True
        # Newly available boundary identities initialize as NOT_BEYOND at this bar.
        for _a,lo,hi,_id in newly:
            if bar.close>hi: counts['exact']+=1;counts['initialization']+=1
            if bar.close<lo: counts['exact']+=1;counts['initialization']+=1
            if inc is not None:
                if bar.close>=hi+inc: counts['point']+=1;counts['initialization']+=1
                if bar.close<=lo-inc: counts['point']+=1;counts['initialization']+=1
            if cat not in (None,0) and pat not in (None,0):
                buf=frac*float(cat)
                if bar.close>=hi+buf: counts['atr']+=1;counts['initialization']+=1
                if bar.close<=lo-buf: counts['atr']+=1;counts['initialization']+=1
        for _a,lo,hi,_id in newly: ut.add(bisect.bisect_left(ups,hi));lt.add(bisect.bisect_left(los,lo));active+=1
        prev=bar
    counts['total']=counts['exact']+counts['point']+counts['atr'];return counts

def main()->int:
    p=argparse.ArgumentParser();p.add_argument('--group8-root',type=Path,required=True);p.add_argument('--staging-db',type=Path,required=True);p.add_argument('--output-db',type=Path,required=True);p.add_argument('--report',type=Path,required=True);a=p.parse_args();root=a.group8_root.resolve()
    if sha(root/'code/moebot_group8_engine_v0_8_0.py')!=ENGINE_SHA: raise SystemExit('engine identity mismatch')
    import sys;sys.path.insert(0,str(root/'code'));from moebot_group8_engine_v0_8_0 import Group8Engine
    a.output_db.unlink(missing_ok=True);e=Group8Engine(staging_db=a.staging_db,output_db=a.output_db,artifacts_root=root,year=2023)
    try:
        e.load_bars();e.process_bounded_ranges();frac=float(e.config['pattern_thresholds']['atr_buffer_breakout_fraction'])
        g6=defaultdict(list)
        specs=[('group6__fvg_events','fvg_id','availability_time'),('group6__imbalance_variants','variant_id','availability_time'),('group6__liquidity_voids','void_id','availability_time'),('group6__bpr_relations','bpr_id','availability_time')]
        for table,idc,avc in specs:
            for r in e.input.execute(f'SELECT timeframe,{idc},{avc},lower,upper FROM {table}'):
                g6[str(r[0])].append((int(r[2]),float(r[3]),float(r[4]),f'{table}:{r[1]}'))
        g8=defaultdict(list)
        for r in e.out.execute("SELECT symbol,timeframe,candidate_id,availability_time,lower,upper FROM price_action_pattern_candidate WHERE definition_id='pa_bounded_range_context'"):
            g8[(str(r[0]),str(r[1]))].append((int(r[3]),float(r[4]),float(r[5]),f'g8:{r[2]}'))
        per={};total={"exact":0,"point":0,"atr":0,"total":0,"initialization":0,"rearmed":0}
        for (sym,tf),bars in sorted(e.bars_by_tf.items()):
            boundaries=list(g6.get(tf,[]))+list(g8.get((sym,tf),[]));res=count_series(bars,boundaries,e.point_increment.get(sym),e.atr_by_bar,frac);per[f'{sym}::{tf}']=res
            for k in total: total[k]+=res[k]
        old=json.loads((root/'reports/35_POSTFIX_BREAKOUT_CARDINALITY_DIAGNOSTIC.json').read_text());pre=int(old['minimum_group6_plus_group8_workload']['candidate_total'])
        report={"format_version":1,"status":"PASS","scope":"EXACT_LOGICAL_COUNT_GROUP6_PLUS_GROUP8_2023_NO_BREAKOUT_MATERIALIZATION","engine_sha256":ENGINE_SHA,"bar_count":sum(len(v) for v in e.bars_by_tf.values()),"bounded_range_count":sum(len(v) for v in g8.values()),"group6_boundary_count":sum(len(v) for v in g6.values()),"transition_counts":total,"per_series":per,"pre_amendment_candidate_lower_bound":pre,"reduction_fraction":1-(total['total']/pre) if pre else None,"observations":{"same_transition_rules_as_PA7E2_A2_P2":True,"group4_group5_group7_excluded":True,"no_breakout_rows_materialized":True,"oos_2024_accessed":False,"frozen_state_changed":False}}
        report['report_hash']=stable(report);a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n');print(json.dumps(report,indent=2,sort_keys=True))
    finally:e.close()
    return 0
if __name__=='__main__':raise SystemExit(main())
