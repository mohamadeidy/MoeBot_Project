#!/usr/bin/env python3
"""Exact indexed physical fast path for Group8 structural narratives.

The frozen logical output is unchanged. For each validated displacement leg,
only structure states at the latest causal close_time for the same
(symbol,timeframe,layer) can survive the reference engine's `newer` rejection;
ties at that latest close_time are preserved exactly.
"""
from __future__ import annotations

import bisect
from collections import defaultdict
from typing import Any

from moebot_group8_engine_v0_8_0 import Group8Engine, max_time, normalize_direction


class IndexedStructuralNarrativeEngine(Group8Engine):
    def process_structural_narratives_fast(self) -> None:
        from group8_postprocess_v0_8_0 import continuation_structure_valid

        states=[dict(r) for r in self.input.execute("SELECT * FROM group3__structure_states ORDER BY close_time,state_id")]
        legs=[dict(r) for r in self._validated_legs()]
        symbols=sorted({s for s,_ in self.bars_by_tf});default_symbol=symbols[0] if len(symbols)==1 else "UNKNOWN"

        by_key:dict[tuple[str,str,str],list[dict[str,Any]]]=defaultdict(list)
        for st in states:by_key[(str(st['symbol']),str(st['timeframe']),str(st['layer']))].append(st)
        times={k:[int(x['close_time']) for x in rows] for k,rows in by_key.items()}

        # Reference `later=next(...)` over legs sorted by validation availability.
        next_same_dir:dict[str,dict[int,dict[str,Any]|None]]={}
        for tf in {str(x['timeframe']) for x in legs}:
            mapping={}
            tf_legs=[x for x in legs if str(x['timeframe'])==tf]
            for i,leg in enumerate(tf_legs):
                sd=None
                # Mapping stores first later leg separately for each direction through key tuple below.
                mapping[id(leg)]=None
            next_same_dir[tf]=mapping
        later_lookup:dict[tuple[str,int,str],dict[str,Any]|None]={}
        for tf in {str(x['timeframe']) for x in legs}:
            tf_legs=[x for x in legs if str(x['timeframe'])==tf]
            for i,leg in enumerate(tf_legs):
                cur_av=int(leg['validation_availability'])
                for direction in ('bullish','bearish'):
                    later_lookup[(tf,i,direction)]=next((x for x in tf_legs[i+1:] if normalize_direction(x['direction'])==direction and int(x['validation_availability'])>cur_av),None)

        tf_positions:dict[str,list[dict[str,Any]]]=defaultdict(list)
        for leg in legs:tf_positions[str(leg['timeframe'])].append(leg)
        leg_index_by_identity={(str(leg['timeframe']),str(leg['leg_id']),str(leg['validation_id'])):i for tf,rows in tf_positions.items() for i,leg in enumerate(rows)}

        for leg in legs:
            tf=str(leg['timeframe']);lav=int(leg['validation_availability']);ld=normalize_direction(leg['direction'])
            if ld=='neutral':continue
            # Examine only matching timeframe keys. Each key contributes all states tied at
            # the latest close_time <= leg availability; earlier states are exactly those
            # rejected by the reference engine's newer-state query.
            for key,rows in by_key.items():
                symbol,ktf,layer=key
                if ktf!=tf:continue
                arr=times[key];pos=bisect.bisect_right(arr,lav)
                if pos==0:continue
                latest_time=arr[pos-1];start=bisect.bisect_left(arr,latest_time,0,pos)
                for st in rows[start:pos]:
                    sd=normalize_direction(st['active_bias'] if st['active_bias'] not in (None,'unknown','transition') else st['sequence_bias'])
                    if sd=='neutral' or ld==sd:continue
                    refs=[self._ref('group3','structure_states',st['state_id'],st['close_time'],event_time=st['close_time'],timeframe=st['timeframe'],details={'layer':st['layer']}),self._ref('group6','displacement_legs',leg['leg_id'],leg['availability_time'],event_time=leg['end_time'],timeframe=leg['timeframe']),self._ref('group6','displacement_validation_events',leg['validation_id'],leg['validation_availability'],event_time=leg['validation_confirmation_time'],timeframe=leg['timeframe'])]
                    hid=self._write_hypothesis('pa_structural_pullback',symbol=st['symbol'] or default_symbol,timeframe=st['timeframe'],direction=sd,event_time=int(leg['end_time']),confirmation_time=int(leg['validation_confirmation_time']),availability_time=max_time(st['close_time'],leg['validation_availability']),upstream_refs=refs,evidence_strength={'counter_direction_displacement':1,'structure_layer':st['layer']})
                    dow_def='dow_advancing_structure' if sd=='bullish' else 'dow_declining_structure'
                    dow=self.out.execute("SELECT * FROM school_interpretation WHERE definition_id=? AND timeframe=? AND json_extract(upstream_refs_json,'$[0].source_id')=? ORDER BY availability_time LIMIT 1",(dow_def,st['timeframe'],st['state_id'])).fetchone()
                    if dow:self._write_interpretation('dow_protected_pullback',symbol=st['symbol'] or default_symbol,timeframe=st['timeframe'],direction=sd,event_time=int(leg['end_time']),confirmation_time=int(leg['validation_confirmation_time']),availability_time=max_time(dow['availability_time'],leg['validation_availability']),upstream_refs=[self._ref('group8','school_interpretation',dow['interpretation_id'],dow['availability_time']),self._ref('group8','narrative_hypothesis',hid,max_time(st['close_time'],leg['validation_availability']))])
                    idx=leg_index_by_identity[(tf,str(leg['leg_id']),str(leg['validation_id']))]
                    later=later_lookup.get((tf,idx,sd))
                    if later and continuation_structure_valid(self,st,leg,later,sd):
                        self._write_hypothesis('pa_continuation_after_pullback',symbol=st['symbol'] or default_symbol,timeframe=st['timeframe'],direction=sd,event_time=int(leg['end_time']),confirmation_time=int(later['validation_confirmation_time']),availability_time=max_time(st['close_time'],leg['validation_availability'],later['validation_availability']),upstream_refs=[self._ref('group8','narrative_hypothesis',hid,max_time(st['close_time'],leg['validation_availability'])),self._ref('group6','displacement_legs',later['leg_id'],later['availability_time'],event_time=later['end_time'],timeframe=later['timeframe']),self._ref('group6','displacement_validation_events',later['validation_id'],later['validation_availability'],event_time=later['validation_confirmation_time'],timeframe=later['timeframe'])])

        # PA7-dependent exhaustion remains identical and automatically becomes active
        # when failed-breakout support rows are present in the work database.
        for fb in self.out.execute("SELECT * FROM price_action_pattern_candidate WHERE definition_id='pa_failed_breakout'").fetchall():
            rej=self.out.execute("SELECT * FROM price_action_pattern_candidate WHERE definition_id IN ('pa_pin_bar_like','pa_rejection_close') AND source_bar_id=? AND direction=? ORDER BY candidate_id LIMIT 1",(fb['source_bar_id'],fb['direction'])).fetchone()
            if rej:self._write_hypothesis('pa_exhaustion_failed_breakout',symbol=fb['symbol'],timeframe=fb['timeframe'],direction=fb['direction'],event_time=int(fb['event_time']),confirmation_time=max_time(fb['confirmation_time'],rej['confirmation_time']),availability_time=max_time(fb['availability_time'],rej['availability_time']),upstream_refs=[self._ref('group8','price_action_pattern_candidate',fb['candidate_id'],fb['availability_time']),self._ref('group8','price_action_pattern_candidate',rej['candidate_id'],rej['availability_time'])])
        self.out.commit()
