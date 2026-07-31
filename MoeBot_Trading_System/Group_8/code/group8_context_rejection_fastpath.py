#!/usr/bin/env python3
"""Exact indexed physical fast path for Group8 context-linked rejection.

The frozen logical definition remains unchanged. This replaces repeated
bar×all-boundary enumeration with a static interval index, followed by the exact
same causal availability/lifecycle checks and geometry predicate.

Stage-4 may additionally be executed through a fixed SHA-256 source-candidate
partition plan. Partitioning is physical only: every partition rebuilds the full
read-only causal context and evaluates an exact disjoint subset of source
candidates. The complete ordered union is therefore identical to one-shot
execution.
"""
from __future__ import annotations

import hashlib
import json
from bisect import bisect_right
from dataclasses import dataclass
from typing import Any, Mapping

from moebot_group8_engine_v0_8_0 import Group8Engine, max_time, stable_hash


STAGE4_PARTITION_COUNT = 24
STAGE4_PARTITION_ALGORITHM = "sha256(candidate_id)-mod-24-v1"
STAGE4_PARTITION_PLAN_ID = "g8-stage4-context-rejections-sha256-mod24-v1"


@dataclass(frozen=True)
class BoundaryRecord:
    payload: Mapping[str, Any]
    lower: float
    upper: float


class IntervalNode:
    __slots__ = ("center", "left", "right", "by_lower", "by_upper")
    def __init__(self, rows: list[BoundaryRecord]) -> None:
        mids=sorted((r.lower+r.upper)/2.0 for r in rows);self.center=mids[len(mids)//2]
        left=[];right=[];cross=[]
        for row in rows:
            if row.upper<self.center:left.append(row)
            elif row.lower>self.center:right.append(row)
            else:cross.append(row)
        self.by_lower=sorted(cross,key=lambda r:(r.lower,r.upper,str(r.payload.get('group')),str(r.payload.get('type')),str(r.payload.get('id'))))
        self.by_upper=sorted(cross,key=lambda r:(r.upper,r.lower,str(r.payload.get('group')),str(r.payload.get('type')),str(r.payload.get('id'))),reverse=True)
        self.left=IntervalNode(left) if left else None;self.right=IntervalNode(right) if right else None
    def query(self,lo:float,hi:float,out:list[BoundaryRecord])->None:
        if hi<self.center:
            for row in self.by_lower:
                if row.lower>hi:break
                out.append(row)
            if self.left:self.left.query(lo,hi,out)
        elif lo>self.center:
            for row in self.by_upper:
                if row.upper<lo:break
                out.append(row)
            if self.right:self.right.query(lo,hi,out)
        else:
            out.extend(self.by_lower)
            if self.left:self.left.query(lo,hi,out)
            if self.right:self.right.query(lo,hi,out)


class IndexedContextRejectionEngine(Group8Engine):
    def _context_boundary_catalog(self,symbol:str,tf:str)->list[dict[str,Any]]:
        rows=[]
        for r in self.input.execute("SELECT * FROM group4__zones WHERE symbol=? AND timeframe=?",(symbol,tf)):
            rows.append({'group':'group4','type':'zones','id':r['zone_id'],'availability':int(r['available_at']),'event':int(r['origin_time']),'lower':float(r['lower']),'upper':float(r['upper']),'expires_at':int(r['expires_at']) if r['expires_at'] is not None else None,'base_status':str(r['status'])})
        for r in self.input.execute("SELECT * FROM group5__liquidity_pools WHERE symbol=? AND timeframe=?",(symbol,tf)):
            seen=set()
            for label,val in [('anchor',r['anchor_price']),('lower',r['lower']),('upper',r['upper'])]:
                if val is None or float(val) in seen:continue
                seen.add(float(val));rows.append({'group':'group5','type':'liquidity_pools','id':f"{r['pool_id']}:{label}",'source_id':r['pool_id'],'availability':int(r['available_at']),'event':int(r['origin_time']),'lower':float(val),'upper':float(val),'expires_at':int(r['expires_at']) if r['expires_at'] is not None else None})
        for t,idc,avc,lowc,upc,eventc in [('fvg_events','fvg_id','availability_time','lower','upper','creation_time'),('imbalance_variants','variant_id','availability_time','lower','upper','availability_time'),('liquidity_voids','void_id','availability_time','lower','upper','start_time'),('bpr_relations','bpr_id','availability_time','lower','upper','creation_time')]:
            cols={x[1] for x in self.input.execute(f"PRAGMA table_info('group6__{t}')")};event_expr=eventc if eventc in cols else avc
            where="timeframe=?";params:[Any]=[tf]
            if 'symbol' in cols:where+=" AND symbol=?";params.append(symbol)
            for r in self.input.execute(f"SELECT {idc} id,{avc} av,{lowc} lo,{upc} hi,{event_expr} ev FROM group6__{t} WHERE {where}",params):
                rows.append({'group':'group6','type':t,'id':r['id'],'availability':int(r['av']),'event':int(r['ev']),'lower':float(r['lo']),'upper':float(r['hi'])})
        g7cols={x[1] for x in self.input.execute("PRAGMA table_info('group7__institutional_zones')")};g7where="timeframe=?";g7params:[Any]=[tf]
        if 'symbol' in g7cols:g7where+=" AND symbol=?";g7params.append(symbol)
        for r in self.input.execute(f"SELECT * FROM group7__institutional_zones WHERE {g7where}",g7params):
            rows.append({'group':'group7','type':'institutional_zones','id':r['zone_id'],'availability':int(r['availability_time']),'event':int(r['event_time']),'lower':float(r['lower']),'upper':float(r['upper'])})
        for r in self.out.execute("SELECT candidate_id,availability_time,event_time,lower,upper FROM price_action_pattern_candidate WHERE definition_id='pa_bounded_range_context' AND symbol=? AND timeframe=?",(symbol,tf)):
            rows.append({'group':'group8','type':'pa_bounded_range_context','id':r['candidate_id'],'availability':int(r['availability_time']),'event':int(r['event_time']),'lower':float(r['lower']),'upper':float(r['upper'])})
        return rows

    @staticmethod
    def _collapse_status_rows(rows:list[Any],time_col:str,status_col:str)->tuple[list[int],list[str]]:
        """Collapse ordered same-time transitions to the exact final SQL tie-break row."""
        times:list[int]=[];statuses:list[str]=[]
        for row in rows:
            t=int(row[time_col]);status=str(row[status_col])
            if times and times[-1]==t:statuses[-1]=status
            else:times.append(t);statuses.append(status)
        return times,statuses

    def _load_status_index_batched(self,table:str,zone_ids:set[str],time_col:str,tie_col:str,status_col:str)->dict[str,tuple[list[int],list[str]]]:
        """Load the same per-zone ordered rows through bounded indexed IN probes."""
        result:dict[str,tuple[list[int],list[str]]]={}
        ordered=sorted(zone_ids)
        for start in range(0,len(ordered),400):
            batch=ordered[start:start+400]
            placeholders=','.join('?' for _ in batch)
            sql=f"SELECT zone_id,{time_col},{tie_col},{status_col} FROM {table} WHERE zone_id IN ({placeholders}) ORDER BY zone_id,{time_col},{tie_col}"
            current=None;rows=[]
            for row in self.input.execute(sql,batch):
                zone_id=str(row['zone_id'])
                if current is not None and zone_id!=current:
                    result[current]=self._collapse_status_rows(rows,time_col,status_col);rows=[]
                current=zone_id;rows.append(row)
            if current is not None:result[current]=self._collapse_status_rows(rows,time_col,status_col)
        return result

    def _build_context_status_indexes(self,g4_zone_ids:set[str],g7_zone_ids:set[str])->None:
        self._g4_transition_index=self._load_status_index_batched('group4__zone_transitions',g4_zone_ids,'transition_time','transition_id','to_status')
        self._g4_interaction_index=self._load_status_index_batched('group4__zone_interactions',g4_zone_ids,'interaction_time','interaction_id','status_after')
        self._g7_transition_index=self._load_status_index_batched('group7__zone_state_transitions',g7_zone_ids,'transition_time','transition_ordinal','status')

    @staticmethod
    def _status_at(index:dict[str,tuple[list[int],list[str]]],zone_id:str,availability:int)->str|None:
        rec=index.get(zone_id)
        if not rec:return None
        times,statuses=rec;i=bisect_right(times,availability)-1
        return statuses[i] if i>=0 else None

    def _context_boundary_active(self,bnd:Mapping[str,Any],availability:int)->bool:
        if int(bnd['availability'])>availability:return False
        expires=bnd.get('expires_at')
        if expires is not None and int(expires)<availability:return False
        if bnd['group']=='group4':
            status=self._status_at(self._g4_transition_index,str(bnd['id']),availability)
            if status is None:status=self._status_at(self._g4_interaction_index,str(bnd['id']),availability)
            return self._status_active(status if status is not None else 'active')
        if bnd['group']=='group7':
            status=self._status_at(self._g7_transition_index,str(bnd['id']),availability)
            return status is None or self._status_active(status)
        return True

    def _apply_physical_sqlite_tuning(self)->None:
        """Apply connection-local performance settings without changing logical data."""
        for conn in (self.input,self.out):
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.execute("PRAGMA cache_size=-1048576")
            conn.execute("PRAGMA mmap_size=4294967296")
        self.out.execute("PRAGMA synchronous=OFF")
        self.out.execute("PRAGMA journal_mode=MEMORY")

    @staticmethod
    def _partition_for_candidate(candidate_id:str,partition_count:int=STAGE4_PARTITION_COUNT)->int:
        if partition_count<=0:raise ValueError('partition_count must be positive')
        digest=hashlib.sha256(str(candidate_id).encode('utf-8')).digest()
        return int.from_bytes(digest[:8],'big',signed=False)%partition_count

    @classmethod
    def stage4_partition_plan(cls)->dict[str,Any]:
        partitions=[{'index':i,'identity':f'{STAGE4_PARTITION_PLAN_ID}:{i:02d}'} for i in range(STAGE4_PARTITION_COUNT)]
        payload={'plan_id':STAGE4_PARTITION_PLAN_ID,'algorithm':STAGE4_PARTITION_ALGORITHM,'partition_count':STAGE4_PARTITION_COUNT,'partitions':partitions}
        return {**payload,'plan_hash':stable_hash(payload)}

    def _record_stage4_partition_receipt(self,partition_index:int,source_ids:list[str],output_ids:list[str])->dict[str,Any]:
        plan=self.stage4_partition_plan()
        payload={'plan_id':plan['plan_id'],'plan_hash':plan['plan_hash'],'partition_index':partition_index,'partition_identity':plan['partitions'][partition_index]['identity'],'source_count':len(source_ids),'source_ids_hash':stable_hash(sorted(source_ids)),'output_count':len(output_ids),'output_ids_hash':stable_hash(sorted(output_ids))}
        receipt={**payload,'receipt_hash':stable_hash(payload)}
        key=f"physical_stage4_partition_receipt:{plan['plan_hash']}:{partition_index:02d}"
        value=json.dumps(receipt,sort_keys=True,separators=(',',':'))
        existing=self.out.execute("SELECT value FROM metadata WHERE key=?",(key,)).fetchone()
        if existing is not None and str(existing[0])!=value:raise RuntimeError(f'conflicting stage-4 partition receipt:{partition_index}')
        self.out.execute("INSERT OR IGNORE INTO metadata(key,value) VALUES(?,?)",(key,value))
        return receipt

    def verify_stage4_partition_coverage(self)->dict[str,Any]:
        plan=self.stage4_partition_plan();receipts=[]
        for i in range(STAGE4_PARTITION_COUNT):
            key=f"physical_stage4_partition_receipt:{plan['plan_hash']}:{i:02d}"
            row=self.out.execute("SELECT value FROM metadata WHERE key=?",(key,)).fetchone()
            if row is None:raise RuntimeError(f'missing stage-4 partition receipt:{i}')
            receipt=json.loads(str(row[0]));payload={k:v for k,v in receipt.items() if k!='receipt_hash'}
            if receipt.get('receipt_hash')!=stable_hash(payload):raise RuntimeError(f'invalid stage-4 partition self-hash:{i}')
            if receipt.get('partition_index')!=i or receipt.get('partition_identity')!=plan['partitions'][i]['identity']:raise RuntimeError(f'stage-4 partition identity mismatch:{i}')
            receipts.append(receipt)
        aggregate={'plan_id':plan['plan_id'],'plan_hash':plan['plan_hash'],'ordered_receipt_hashes':[r['receipt_hash'] for r in receipts],'source_count':sum(int(r['source_count']) for r in receipts),'output_count':sum(int(r['output_count']) for r in receipts)}
        return {**aggregate,'aggregate_hash':stable_hash(aggregate)}

    def process_context_rejections_fast(self,partition_index:int|None=None)->dict[str,Any]|None:
        self._apply_physical_sqlite_tuning()
        if partition_index is not None and not (0<=partition_index<STAGE4_PARTITION_COUNT):raise ValueError(f'invalid stage-4 partition:{partition_index}')
        rejections=self.out.execute("SELECT * FROM price_action_pattern_candidate WHERE definition_id IN ('pa_pin_bar_like','pa_rejection_close') ORDER BY availability_time,candidate_id").fetchall()
        if partition_index is not None:rejections=[p for p in rejections if self._partition_for_candidate(str(p['candidate_id']))==partition_index]
        indices={};catalogs={}
        for key in self.bars_by_tf:
            catalog=self._context_boundary_catalog(*key);catalogs[key]=catalog
            rows=[BoundaryRecord(b,float(b['lower']),float(b['upper'])) for b in catalog];indices[key]=IntervalNode(rows) if rows else None
        g4_zone_ids={str(b['id']) for catalog in catalogs.values() for b in catalog if b['group']=='group4'}
        g7_zone_ids={str(b['id']) for catalog in catalogs.values() for b in catalog if b['group']=='group7'}
        self._build_context_status_indexes(g4_zone_ids,g7_zone_ids)
        output_ids=[]
        for p in rejections:
            bar=self._bar_by_id(p['source_bar_id'])
            if bar is None:continue
            atr=self.atr_by_bar.get(bar.id);increment=self.point_increment.get(bar.symbol);tol=max([x for x in (increment,(self.config['feature_parameters']['proximity_atr_fraction']*atr if atr else None)) if x is not None],default=0.0);pl,pu=float(p['lower']),float(p['upper']);matches=[];tree=indices.get((bar.symbol,bar.timeframe))
            if tree:tree.query(pl-tol,pu+tol,matches)
            for rec in matches:
                bnd=rec.payload
                if not self._context_boundary_active(bnd,int(p['availability_time'])):continue
                bl,bu=float(bnd['lower']),float(bnd['upper']);overlap=max(0.0,min(pu,bu)-max(pl,bl));distance=0.0 if overlap>0 else min(abs(pl-bu),abs(bl-pu))
                if overlap<=0 and distance>tol:continue
                output_ids.append(self._write_pattern('pa_context_linked_rejection',symbol=bar.symbol,timeframe=bar.timeframe,direction=p['direction'],source_bar_id=bar.id,event_time=int(p['event_time']),confirmation_time=int(p['confirmation_time']),availability_time=max_time(p['availability_time'],bnd['availability']),lower=pl,upper=pu,ambiguous=bool(p['ambiguous']),features={'overlap':overlap,'distance':distance,'tolerance':tol,'boundary_identity':bnd['id']},upstream_refs=[self._ref('group8','price_action_pattern_candidate',p['candidate_id'],p['availability_time']),self._ref(bnd['group'],bnd['type'],bnd.get('source_id',bnd['id']),bnd['availability'],event_time=bnd['event'],timeframe=bar.timeframe)]))
        receipt=None
        if partition_index is not None:receipt=self._record_stage4_partition_receipt(partition_index,[str(p['candidate_id']) for p in rejections],output_ids)
        self.out.commit();return receipt
