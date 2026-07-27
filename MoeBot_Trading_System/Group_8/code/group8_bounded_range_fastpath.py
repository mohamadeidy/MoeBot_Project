#!/usr/bin/env python3
"""Exact physical fast path for frozen Group 8 bounded-range construction.

The frozen rule chooses the active Group4 zone(s) with maximum `upper` strictly
below each bar close and minimum `lower` strictly above it, independently per
layer. This implementation indexes prices and lifecycle histories so it does not
scan every zone for every bar. Logical writes are delegated to the frozen engine.
"""
from __future__ import annotations
import bisect
from collections import defaultdict
from typing import Any

from moebot_group8_engine_v0_8_0 import Group8Engine,max_time


class IndexedBoundedRangeEngine(Group8Engine):
    def _zone_status_histories(self):
        trans=defaultdict(list); inter=defaultdict(list)
        for r in self.input.execute("SELECT zone_id,transition_time,transition_id,to_status FROM group4__zone_transitions ORDER BY zone_id,transition_time,transition_id"):
            trans[str(r['zone_id'])].append((int(r['transition_time']),str(r['transition_id']),str(r['to_status'])))
        for r in self.input.execute("SELECT zone_id,interaction_time,interaction_id,status_after FROM group4__zone_interactions ORDER BY zone_id,interaction_time,interaction_id"):
            inter[str(r['zone_id'])].append((int(r['interaction_time']),str(r['interaction_id']),str(r['status_after'])))
        return trans,inter

    @staticmethod
    def _latest_status(history:list[tuple[int,str,str]],t:int):
        if not history:return None
        pos=bisect.bisect_right(history,(int(t),chr(0x10ffff),chr(0x10ffff)))-1
        return history[pos][2] if pos>=0 else None

    def process_bounded_ranges_fast(self)->None:
        transitions,interactions=self._zone_status_histories()
        for (symbol,tf),bars in sorted(self.bars_by_tf.items()):
            zones=[dict(r) for r in self.input.execute("SELECT * FROM group4__zones WHERE symbol=? AND timeframe=? ORDER BY available_at,zone_id",(symbol,tf))]
            by_layer=defaultdict(list)
            for z in zones:by_layer[str(z['layer'])].append(z)
            for layer,zs in sorted(by_layer.items()):
                upper_groups=defaultdict(list);lower_groups=defaultdict(list)
                for z in zs:
                    upper_groups[float(z['upper'])].append(z);lower_groups[float(z['lower'])].append(z)
                upper_values=sorted(upper_groups);lower_values=sorted(lower_groups)
                for v in upper_groups:upper_groups[v].sort(key=lambda z:str(z['zone_id']))
                for v in lower_groups:lower_groups[v].sort(key=lambda z:str(z['zone_id']))

                def active(z,t):
                    if int(z['available_at'])>t:return False
                    if z['expires_at'] is not None and int(z['expires_at'])<t:return False
                    zid=str(z['zone_id'])
                    # Exact frozen helper precedence: if any transition exists at/before
                    # t it wins; interaction history is consulted only when no such
                    # transition exists. With neither, frozen helper returns 'active'.
                    st=self._latest_status(transitions.get(zid,[]),t)
                    if st is None:st=self._latest_status(interactions.get(zid,[]),t)
                    return self._status_active(st or 'active')

                for bar in bars:
                    t=int(bar.available_at);close=float(bar.close)
                    below=[];above=[]
                    i=bisect.bisect_left(upper_values,close)-1
                    while i>=0 and not below:
                        level=upper_values[i];below=[z for z in upper_groups[level] if active(z,t)];i-=1
                    j=bisect.bisect_right(lower_values,close)
                    while j<len(lower_values) and not above:
                        level=lower_values[j];above=[z for z in lower_groups[level] if active(z,t)];j+=1
                    if not below or not above:continue
                    for lo in below:
                        for hi in above:
                            lower,upper=float(lo['upper']),float(hi['lower'])
                            if lower>=upper:continue
                            avail=max_time(bar.available_at,lo['available_at'],hi['available_at'])
                            self._write_pattern('pa_bounded_range_context',symbol=symbol,timeframe=tf,direction='neutral',source_bar_id=bar.id,event_time=bar.close_time,confirmation_time=bar.close_time,availability_time=avail,lower=lower,upper=upper,features={'midpoint':(lower+upper)/2,'layer':layer,'lower_zone_id':lo['zone_id'],'upper_zone_id':hi['zone_id']},upstream_refs=[self._ref('source','bars',bar.id,bar.available_at,event_time=bar.close_time,timeframe=tf),self._ref('group4','zones',lo['zone_id'],lo['available_at'],event_time=lo['origin_time'],timeframe=tf),self._ref('group4','zones',hi['zone_id'],hi['available_at'],event_time=hi['origin_time'],timeframe=tf)])
        self.out.commit()
