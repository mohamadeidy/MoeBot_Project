#!/usr/bin/env python3
"""Exact indexed physical fast path for Group8 context-linked rejection.

The frozen logical definition remains unchanged. This replaces repeated
bar×all-boundary enumeration with a static interval index, followed by the exact
same causal availability/lifecycle checks and geometry predicate.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from moebot_group8_engine_v0_8_0 import Group8Engine, max_time


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
            for r in self.input.execute(f"SELECT {idc} id,{avc} av,{lowc} lo,{upc} hi,{event_expr} ev FROM group6__{t} WHERE timeframe=?",(tf,)):
                rows.append({'group':'group6','type':t,'id':r['id'],'availability':int(r['av']),'event':int(r['ev']),'lower':float(r['lo']),'upper':float(r['hi'])})
        for r in self.input.execute("SELECT * FROM group7__institutional_zones WHERE timeframe=?",(tf,)):
            rows.append({'group':'group7','type':'institutional_zones','id':r['zone_id'],'availability':int(r['availability_time']),'event':int(r['event_time']),'lower':float(r['lower']),'upper':float(r['upper'])})
        for r in self.out.execute("SELECT candidate_id,availability_time,event_time,lower,upper FROM price_action_pattern_candidate WHERE definition_id='pa_bounded_range_context' AND symbol=? AND timeframe=?",(symbol,tf)):
            rows.append({'group':'group8','type':'pa_bounded_range_context','id':r['candidate_id'],'availability':int(r['availability_time']),'event':int(r['event_time']),'lower':float(r['lower']),'upper':float(r['upper'])})
        return rows

    def _context_boundary_active(self,bnd:Mapping[str,Any],availability:int)->bool:
        if int(bnd['availability'])>availability:return False
        expires=bnd.get('expires_at')
        if expires is not None and int(expires)<availability:return False
        if bnd['group']=='group4':return self._status_active(self._active_zone_status_at(str(bnd['id']),str(bnd.get('base_status','active')),availability))
        if bnd['group']=='group7':
            tr=self.input.execute("SELECT status FROM group7__zone_state_transitions WHERE zone_id=? AND transition_time<=? ORDER BY transition_time DESC,transition_ordinal DESC LIMIT 1",(bnd['id'],availability)).fetchone();return not tr or self._status_active(str(tr[0]))
        return True

    def process_context_rejections_fast(self)->None:
        rejections=self.out.execute("SELECT * FROM price_action_pattern_candidate WHERE definition_id IN ('pa_pin_bar_like','pa_rejection_close') ORDER BY availability_time,candidate_id").fetchall();indices={}
        for key in self.bars_by_tf:
            rows=[BoundaryRecord(b,float(b['lower']),float(b['upper'])) for b in self._context_boundary_catalog(*key)];indices[key]=IntervalNode(rows) if rows else None
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
                self._write_pattern('pa_context_linked_rejection',symbol=bar.symbol,timeframe=bar.timeframe,direction=p['direction'],source_bar_id=bar.id,event_time=int(p['event_time']),confirmation_time=int(p['confirmation_time']),availability_time=max_time(p['availability_time'],bnd['availability']),lower=pl,upper=pu,ambiguous=bool(p['ambiguous']),features={'overlap':overlap,'distance':distance,'tolerance':tol,'boundary_identity':bnd['id']},upstream_refs=[self._ref('group8','price_action_pattern_candidate',p['candidate_id'],p['availability_time']),self._ref(bnd['group'],bnd['type'],bnd.get('source_id',bnd['id']),bnd['availability'],event_time=bnd['event'],timeframe=bar.timeframe)])
        self.out.commit()
