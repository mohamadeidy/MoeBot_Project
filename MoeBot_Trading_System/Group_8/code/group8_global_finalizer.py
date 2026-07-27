#!/usr/bin/env python3
"""Finalize the sharded Group 8 annual domain without re-materializing PA7 rows.

Input working DB: exact Annual Core plus PA7-dependent derived rows.
Input PA7 catalog: infrastructure-only query projection of the lossless PA7 shards.
Output working DB remains the non-PA7/global domain artifact; PA7 candidates/states
remain in their own shards. Logical semantics are identical to the frozen engine.
"""
from __future__ import annotations
import argparse,json
from collections import defaultdict
from pathlib import Path
from typing import Any,Mapping

from group8_pa7_derived_executor import PA7DerivedEngine
from moebot_group8_engine_v0_8_0 import canonical_json,deterministic_id,stable_hash,max_time,normalize_direction
from group8_postprocess_v0_8_0 import (
    DOW_INVALIDATABLE,WYCKOFF_INVALIDATABLE,WYCKOFF_COMPLETED_HYPOTHESES,
    _finalize_bounded_ranges,_first_opposite_group3_event,_terminal_event_for_hypothesis,
    ensure_initial_hypothesis_lifecycle,ensure_contradicted,ensure_terminal_hypothesis_state,
    write_invalidation,_validate_persistence,opposite_direction,
)

PA7_DEFS={'pa_breakout_exact','pa_breakout_point_buffer','pa_breakout_atr_buffer','pa_failed_breakout','pa_retest'}

class Group8GlobalFinalizer(PA7DerivedEngine):
    def _pa7_by_id(self,candidate_id:str):
        return self.pa7.execute('SELECT * FROM pa7_candidate_catalog WHERE candidate_id=?',(str(candidate_id),)).fetchone()

    def _first_pa7_at_level(self,*,symbol:str,timeframe:str,level:float,direction:str,after_time:int,failed_only:bool=False):
        definition='pa_failed_breakout' if failed_only else 'pa_breakout_exact';d=normalize_direction(direction)
        return self.pa7.execute('''SELECT * FROM pa7_candidate_catalog
            WHERE definition_id=? AND symbol=? AND timeframe=? AND availability_time>? AND direction=?
              AND ABS(lower-?)<=1e-12 ORDER BY availability_time,candidate_id LIMIT 1''',
            (definition,symbol,timeframe,int(after_time),d,float(level))).fetchone()

    def _range_candidate_for_interpretation(self,interpretation:Any):
        refs=json.loads(interpretation['upstream_refs_json'])
        for ref in refs:
            if ref.get('source_group')=='group8' and ref.get('source_type')=='price_action_pattern_candidate':
                row=self.out.execute('SELECT * FROM price_action_pattern_candidate WHERE candidate_id=?',(str(ref['source_id']),)).fetchone()
                if row is not None and row['definition_id']=='pa_bounded_range_context':return row
        for ref in refs:
            if ref.get('source_group')=='group8' and ref.get('source_type')=='school_interpretation':
                row=self.out.execute('SELECT * FROM school_interpretation WHERE interpretation_id=?',(str(ref['source_id']),)).fetchone()
                if row is not None and row['definition_id']=='wyckoff_range_context':return self._range_candidate_for_interpretation(row)
        return None

    def _interpretation_level_context(self,interpretation:Any):
        definition=str(interpretation['definition_id']);refs=json.loads(interpretation['upstream_refs_json'])
        if definition in {'wyckoff_spring_candidate','wyckoff_upthrust_candidate'}:
            rg=self._range_candidate_for_interpretation(interpretation)
            if rg is None:return None,None
            return float(rg['lower'] if definition=='wyckoff_spring_candidate' else rg['upper']),('bearish' if definition=='wyckoff_spring_candidate' else 'bullish')
        if definition in {'wyckoff_sign_of_strength','wyckoff_sign_of_weakness'}:
            ref=next((r for r in refs if r.get('source_group')=='group8' and r.get('source_type')=='price_action_pattern_candidate'),None)
            br=self._pa7_by_id(str(ref['source_id'])) if ref else None
            if br is None:return None,None
            feats=json.loads(br['features_json']);level=feats.get('locked_level',br['lower'])
            return float(level),('bearish' if definition=='wyckoff_sign_of_strength' else 'bullish')
        if definition in {'wyckoff_last_point_of_support','wyckoff_last_point_of_supply'}:
            ref=next((r for r in refs if r.get('source_group')=='group8' and r.get('source_type')=='school_interpretation'),None)
            sign=self.out.execute('SELECT * FROM school_interpretation WHERE interpretation_id=?',(str(ref['source_id']),)).fetchone() if ref else None
            return self._interpretation_level_context(sign) if sign is not None else (None,None)
        return None,None

    def _terminal(self,hypothesis:Any):
        if str(hypothesis['definition_id'])!='pa_exhaustion_failed_breakout':return _terminal_event_for_hypothesis(self,hypothesis)
        refs=json.loads(hypothesis['upstream_refs_json']);ref=next((r for r in refs if r.get('source_group')=='group8' and r.get('source_type')=='price_action_pattern_candidate'),None);failed=self._pa7_by_id(str(ref['source_id'])) if ref else None
        if failed is None:return None
        feats=json.loads(failed['features_json']);level=feats.get('locked_level')
        if level is None:return None
        later=self._first_pa7_at_level(symbol=hypothesis['symbol'],timeframe=hypothesis['timeframe'],level=float(level),direction=opposite_direction(hypothesis['direction']) or 'neutral',after_time=int(hypothesis['availability_time']),failed_only=False)
        if later is None:return None
        return {'state':'invalidated','source_type':'price_action_pattern_candidate','source_id':later['candidate_id'],'event_time':int(later['event_time']),'confirmation_time':int(later['confirmation_time']),'availability_time':int(later['availability_time']),'details':{'rule':'pa_exhaustion_failed_breakout.invalidation_rule','locked_level':float(level)}}

    def process_cross_school_and_mtf_reference_order(self)->None:
        # Reconstruct frozen row-production stage order. The sharded core inserts ICT
        # before PA7-derived Wyckoff signs; the monolithic frozen engine inserts all
        # Wyckoff interpretations before ICT. MTF relation orientation depends on this
        # row traversal order, so make it explicit rather than planner/rowid-dependent.
        pre_dow={'dow_advancing_structure','dow_declining_structure','dow_indeterminate_structure','dow_bullish_transition','dow_bearish_transition'}
        wy_pre={'wyckoff_range_context','wyckoff_spring_candidate','wyckoff_upthrust_candidate'}
        wy_post={'wyckoff_sign_of_strength','wyckoff_sign_of_weakness','wyckoff_last_point_of_support','wyckoff_last_point_of_supply'}
        def rank(d:str)->int:
            if d in pre_dow:return 1
            if d=='dow_protected_pullback':return 2
            if d in wy_pre:return 3
            if d in wy_post:return 4
            if d.startswith('ict_'):return 5
            return 9
        interps=[dict(r) for r in self.out.execute('SELECT rowid,* FROM school_interpretation')];interps.sort(key=lambda r:(rank(str(r['definition_id'])),int(r['rowid'])))
        hypotheses=[dict(r) for r in self.out.execute('SELECT rowid,* FROM narrative_hypothesis ORDER BY rowid')]
        subjects=[]
        for r in interps:subjects.append({'type':'school_interpretation','id':r['interpretation_id'],'school_id':r['school_id'],'symbol':r['symbol'],'timeframe':r['timeframe'],'direction':r['direction'],'event_time':r['event_time'],'availability_time':r['availability_time'],'upstream_refs_json':r['upstream_refs_json']})
        for r in hypotheses:subjects.append({'type':'narrative_hypothesis','id':r['hypothesis_id'],'school_id':r['school_id'],'symbol':r['symbol'],'timeframe':r['timeframe'],'direction':r['direction'],'event_time':r['event_time'],'availability_time':r['availability_time'],'upstream_refs_json':r['upstream_refs_json']})
        by_source:dict[tuple[str,str,str],list[dict[str,Any]]]=defaultdict(list)
        for s in subjects:
            for ref in json.loads(s['upstream_refs_json']):by_source[(str(ref.get('source_group')),str(ref.get('source_type')),str(ref.get('source_id')))].append(s)
        for key,subs in by_source.items():
            schools={s['school_id'] for s in subs}
            if len(subs)<2 or len(schools)<2:continue
            ids=sorted(s['id'] for s in subs);avail=max(int(s['availability_time']) for s in subs);payload={'source':key,'subject_ids':ids,'availability_time':avail,'relation_type':'same_immutable_upstream_evidence'};sid=deterministic_id('g8shared',payload);h=stable_hash(payload);row={'shared_evidence_id':sid,'source_group':key[0],'source_type':key[1],'source_id':key[2],'subject_ids_json':canonical_json(ids),'relation_type':'same_immutable_upstream_evidence','availability_time':avail,'details_json':canonical_json({'school_count':len(schools)}),'shared_evidence_hash':h};self._insert_immutable('shared_evidence','shared_evidence_id',sid,row,hash_column='shared_evidence_hash',expected_hash=h)
            dirs={s['direction'] for s in subs if s['direction'] not in ('neutral','unknown')}
            if 'bullish' in dirs and 'bearish' in dirs:
                for a in subs:
                    for b in subs:
                        if a['id']>=b['id'] or a['school_id']==b['school_id'] or a['direction']==b['direction']:continue
                        av=max_time(a['availability_time'],b['availability_time']);p={'left':a['id'],'right':b['id'],'type':'opposing_descriptive_claim_same_evidence','availability':av};cid=deterministic_id('g8conf',p);ch=stable_hash(p);r={'conflict_id':cid,'left_subject_type':a['type'],'left_subject_id':a['id'],'right_subject_type':b['type'],'right_subject_id':b['id'],'conflict_type':'opposing_descriptive_claim_same_evidence','event_time':max_time(a['event_time'],b['event_time']),'availability_time':av,'details_json':canonical_json({'shared_source':key}),'conflict_hash':ch};self._insert_immutable('conflicting_evidence','conflict_id',cid,r,hash_column='conflict_hash',expected_hash=ch)
        tf_seconds={r['timeframe']:int(r['seconds']) for r in self.input.execute('SELECT * FROM group2__timeframe_dictionary')};ordered=[s for s in subjects if s['timeframe'] in tf_seconds];by_symbol:dict[str,list[dict[str,Any]]]=defaultdict(list)
        for s in ordered:by_symbol[s['symbol']].append(s)
        for symbol,subs in by_symbol.items():
            for i,a in enumerate(subs):
                for b in subs[i+1:]:
                    if a['timeframe']==b['timeframe']:continue
                    if abs(int(a['event_time'])-int(b['event_time']))>max(tf_seconds[a['timeframe']],tf_seconds[b['timeframe']])*2:continue
                    rel='same-direction context' if a['direction']==b['direction'] and a['direction']!='neutral' else 'opposing-direction context' if {a['direction'],b['direction']}=={'bullish','bearish'} else 'partial overlap';p={'a':a['id'],'b':b['id'],'relation':rel,'availability':max_time(a['availability_time'],b['availability_time'])};rid=deterministic_id('g8mtf',p);h=stable_hash(p);r={'relation_id':rid,'subject_type':a['type'],'subject_id':a['id'],'subject_timeframe':a['timeframe'],'object_type':b['type'],'object_id':b['id'],'object_timeframe':b['timeframe'],'relation_type':rel,'event_time':max_time(a['event_time'],b['event_time']),'availability_time':p['availability'],'overlap_ratio':None,'details_json':canonical_json({'timeframe_seconds':{a['timeframe']:tf_seconds[a['timeframe']],b['timeframe']:tf_seconds[b['timeframe']]}}),'relation_hash':h};self._insert_immutable('multi_timeframe_context_relation','relation_id',rid,r,hash_column='relation_hash',expected_hash=h)
        self.out.commit()

    def persist_hypothesis_lifecycle_catalog(self)->None:
        for h in self.out.execute('SELECT * FROM narrative_hypothesis ORDER BY availability_time,hypothesis_id').fetchall():
            ensure_initial_hypothesis_lifecycle(self,h['hypothesis_id'],h['initial_state'],event_time=int(h['event_time']),availability_time=int(h['availability_time']))
            terminal=self._terminal(h);conflicts=[]
            for c in self.out.execute("SELECT * FROM conflicting_evidence WHERE (left_subject_type='narrative_hypothesis' AND left_subject_id=?) OR (right_subject_type='narrative_hypothesis' AND right_subject_id=?) ORDER BY availability_time,conflict_id",(h['hypothesis_id'],h['hypothesis_id'])):
                if int(c['availability_time'])>=int(h['availability_time']):conflicts.append(c)
            if conflicts:
                first=conflicts[0];tt=terminal['availability_time'] if terminal is not None else None
                if tt is None or int(first['availability_time'])<=int(tt):ensure_contradicted(self,h['hypothesis_id'],source_type='conflicting_evidence',source_id=first['conflict_id'],event_time=int(first['event_time']),availability_time=int(first['availability_time']),details={'conflict_type':first['conflict_type']})
            if terminal is not None:
                ensure_terminal_hypothesis_state(self,h['hypothesis_id'],terminal['state'],source_type=terminal['source_type'],source_id=str(terminal['source_id']),event_time=int(terminal['event_time']),availability_time=int(terminal['availability_time']),details=terminal['details'])
                if terminal['state']=='invalidated':write_invalidation(self,subject_type='narrative_hypothesis',subject_id=h['hypothesis_id'],rule_id=f"{h['definition_id']}.invalidation_rule",source_type=terminal['source_type'],source_id=str(terminal['source_id']),event_time=int(terminal['event_time']),confirmation_time=int(terminal['confirmation_time']),availability_time=int(terminal['availability_time']),reasons=['frozen_invalidation_rule_satisfied'],details=terminal['details'])
            else:
                end=int(self.annual_end_time or h['availability_time']);ensure_terminal_hypothesis_state(self,h['hypothesis_id'],'right_censored',source_type='annual_end',source_id=str(self.year),event_time=end,availability_time=end,details={'rule':'no_terminal_frozen_event_available_before_annual_end'})
        self.out.commit()

    def persist_interpretation_invalidations_catalog(self)->None:
        for i in self.out.execute('SELECT * FROM school_interpretation ORDER BY availability_time,interpretation_id').fetchall():
            d=str(i['definition_id']);inv=None
            if d in DOW_INVALIDATABLE:
                layer=None
                for ref in json.loads(i['upstream_refs_json']):
                    det=ref.get('details') or {}
                    if det.get('layer') is not None:layer=str(det['layer']);break
                inv=_first_opposite_group3_event(self,symbol=i['symbol'],timeframe=i['timeframe'],layer=layer,direction=i['direction'],after_time=int(i['availability_time']),through_time=None)
            elif d in WYCKOFF_INVALIDATABLE:
                level,idir=self._interpretation_level_context(i)
                if level is not None and idir is not None:
                    later=self._first_pa7_at_level(symbol=i['symbol'],timeframe=i['timeframe'],level=level,direction=idir,after_time=int(i['availability_time']),failed_only=d in {'wyckoff_sign_of_strength','wyckoff_sign_of_weakness','wyckoff_last_point_of_support','wyckoff_last_point_of_supply'})
                    if later is not None:inv={'source_type':'price_action_pattern_candidate','source_id':later['candidate_id'],'event_time':int(later['event_time']),'confirmation_time':int(later['confirmation_time']),'availability_time':int(later['availability_time']),'details':{'locked_level':level,'invalidating_definition':later['definition_id']}}
            if inv is not None:write_invalidation(self,subject_type='school_interpretation',subject_id=i['interpretation_id'],rule_id=f'{d}.invalidation_rule',source_type=inv['source_type'],source_id=str(inv['source_id']),event_time=int(inv['event_time']),confirmation_time=int(inv['confirmation_time']),availability_time=int(inv['availability_time']),reasons=['frozen_invalidation_rule_satisfied'],details=inv['details'])
        self.out.commit()

    def run_global_finalizer(self)->dict[str,Any]:
        self.load_bars();self.process_cross_school_and_mtf_reference_order();_finalize_bounded_ranges(self);self.persist_hypothesis_lifecycle_catalog();self.persist_interpretation_invalidations_catalog();persistence=_validate_persistence(self);audit=self.audit(require_all_definitions_producible=False)
        if persistence['status']!='PASS' or audit['status']!='PASS':raise RuntimeError(f'global finalizer audit failed persistence={persistence} audit={audit}')
        return {'format_version':1,'status':'PASS','year':self.year,'physical_role':'GLOBAL_NON_PA7_FINALIZER','persistence':persistence,'audit':audit,'free_only':True,'paid_runner_allowed':False,'paid_service_allowed':False,'oos_2024_accessed':self.year==2024}

def main()->int:
    p=argparse.ArgumentParser();p.add_argument('--staging-db',type=Path,required=True);p.add_argument('--working-db',type=Path,required=True);p.add_argument('--pa7-catalog',type=Path,required=True);p.add_argument('--artifacts-root',type=Path,required=True);p.add_argument('--year',type=int,required=True);p.add_argument('--symbol');p.add_argument('--report',type=Path);a=p.parse_args()
    if a.year==2024:
        s=json.loads((a.artifacts_root/'STATUS.json').read_text())
        if s.get('annual_execution_2024_authorized') is not True:raise SystemExit('2024 OOS is forbidden')
    e=Group8GlobalFinalizer(staging_db=a.staging_db,output_db=a.working_db,pa7_catalog=a.pa7_catalog,artifacts_root=a.artifacts_root,year=a.year,symbol=a.symbol)
    try:r=e.run_global_finalizer()
    finally:e.close()
    if a.report:a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(r,indent=2,sort_keys=True)+'\n')
    print(json.dumps(r,indent=2,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
