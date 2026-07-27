#!/usr/bin/env python3
"""Produce PA7-dependent Group8 interpretations/hypotheses from a compact PA7 catalog.

The working output is an Annual Core SQLite copy. PA7 domain rows stay in their
lossless shards; this executor queries only the infrastructure catalog and writes
new Group8 derived domain objects with the frozen engine's immutable writers.
"""
from __future__ import annotations
import argparse,json,sqlite3
from pathlib import Path
from typing import Any

from moebot_group8_engine_v0_8_0 import Group8Engine,max_time,normalize_direction

DERIVED_INTERPRETATIONS={
 'wyckoff_sign_of_strength','wyckoff_sign_of_weakness',
 'wyckoff_last_point_of_support','wyckoff_last_point_of_supply',
}
DERIVED_HYPOTHESES={
 'pa_exhaustion_failed_breakout','wyckoff_accumulation_hypothesis','wyckoff_distribution_hypothesis',
 'wyckoff_reaccumulation_hypothesis','wyckoff_redistribution_hypothesis',
}

class PA7DerivedEngine(Group8Engine):
    def __init__(self,*,pa7_catalog:Path,**kwargs:Any)->None:
        super().__init__(**kwargs)
        self.pa7=sqlite3.connect(f'file:{pa7_catalog.resolve()}?mode=ro',uri=True);self.pa7.row_factory=sqlite3.Row
        qc=self.pa7.execute('PRAGMA quick_check').fetchone()[0]
        if qc!='ok':raise RuntimeError(f'PA7 catalog invalid:{qc}')
    def close(self)->None:
        try:self.pa7.close()
        finally:super().close()

    def _first_exact_at_level(self,*,symbol:str,timeframe:str,direction:str,after_or_equal:int,level:float):
        # The frozen SQLite schema has ix_pa_candidate_tf_avail ending in candidate_id.
        # The reference Wyckoff query orders only by availability_time, and on the
        # frozen schema equal-availability rows are consequently visited by candidate_id.
        # Encode that planner-stable observed order explicitly in the sharded catalog.
        return self.pa7.execute("""SELECT * FROM pa7_candidate_catalog
          WHERE definition_id='pa_breakout_exact' AND symbol=? AND timeframe=? AND direction=?
            AND availability_time>=? AND ABS(lower-?)<1e-12
          ORDER BY availability_time,candidate_id LIMIT 1""",
          (symbol,timeframe,direction,int(after_or_equal),float(level))).fetchone()

    def _first_retest_at_level(self,*,symbol:str,timeframe:str,after:int,level:float):
        # Same frozen index/tie behavior as the reference retest lookup.
        return self.pa7.execute("""SELECT * FROM pa7_candidate_catalog
          WHERE definition_id='pa_retest' AND symbol=? AND timeframe=? AND availability_time>? AND ABS(lower-?)<1e-12
          ORDER BY availability_time,candidate_id LIMIT 1""",
          (symbol,timeframe,int(after),float(level))).fetchone()

    def process_exhaustion_from_catalog(self)->None:
        for fb in self.pa7.execute("SELECT * FROM pa7_candidate_catalog WHERE definition_id='pa_failed_breakout' ORDER BY availability_time,candidate_id"):
            rej=self.out.execute("SELECT * FROM price_action_pattern_candidate WHERE definition_id IN ('pa_pin_bar_like','pa_rejection_close') AND source_bar_id=? AND direction=? ORDER BY candidate_id LIMIT 1",(fb['source_bar_id'],fb['direction'])).fetchone()
            if rej:
                self._write_hypothesis('pa_exhaustion_failed_breakout',symbol=fb['symbol'],timeframe=fb['timeframe'],direction=fb['direction'],event_time=int(fb['event_time']),confirmation_time=max_time(fb['confirmation_time'],rej['confirmation_time']),availability_time=max_time(fb['availability_time'],rej['availability_time']),upstream_refs=[self._ref('group8','price_action_pattern_candidate',fb['candidate_id'],fb['availability_time']),self._ref('group8','price_action_pattern_candidate',rej['candidate_id'],rej['availability_time'])])
        self.out.commit()

    def process_wyckoff_pa7_dependent(self)->None:
        wy_ranges=self.out.execute("SELECT * FROM school_interpretation WHERE definition_id='wyckoff_range_context'").fetchall();valid_legs=[dict(r) for r in self._validated_legs()]
        for wr in wy_ranges:
            rgref=next((x for x in json.loads(wr['upstream_refs_json']) if x.get('source_type')=='price_action_pattern_candidate'),None)
            if not rgref:continue
            rg=self.out.execute('SELECT * FROM price_action_pattern_candidate WHERE candidate_id=?',(rgref['source_id'],)).fetchone()
            if not rg:continue
            for d,definition,breakdir in [('bullish','wyckoff_sign_of_strength','bullish'),('bearish','wyckoff_sign_of_weakness','bearish')]:
                target=float(rg['upper'] if d=='bullish' else rg['lower'])
                for leg in valid_legs:
                    if leg['timeframe']!=wr['timeframe'] or normalize_direction(leg['direction'])!=d:continue
                    br=self._first_exact_at_level(symbol=wr['symbol'],timeframe=wr['timeframe'],direction=breakdir,after_or_equal=int(leg['validation_availability']),level=target)
                    if br is None:continue
                    sign=self._write_interpretation(definition,symbol=wr['symbol'],timeframe=wr['timeframe'],direction=d,event_time=int(br['event_time']),confirmation_time=int(br['confirmation_time']),availability_time=max_time(wr['availability_time'],leg['validation_availability'],br['availability_time']),upstream_refs=[self._ref('group8','school_interpretation',wr['interpretation_id'],wr['availability_time']),self._ref('group6','displacement_legs',leg['leg_id'],leg['availability_time'],event_time=leg['end_time'],timeframe=leg['timeframe']),self._ref('group8','price_action_pattern_candidate',br['candidate_id'],br['availability_time'])])
                    ret=self._first_retest_at_level(symbol=wr['symbol'],timeframe=wr['timeframe'],after=int(br['availability_time']),level=target)
                    if ret:
                        ldef='wyckoff_last_point_of_support' if d=='bullish' else 'wyckoff_last_point_of_supply'
                        self._write_interpretation(ldef,symbol=wr['symbol'],timeframe=wr['timeframe'],direction=d,event_time=int(ret['event_time']),confirmation_time=int(ret['confirmation_time']),availability_time=max_time(wr['availability_time'],leg['validation_availability'],br['availability_time'],ret['availability_time']),upstream_refs=[self._ref('group8','school_interpretation',sign,max_time(wr['availability_time'],leg['validation_availability'],br['availability_time'])),self._ref('group8','price_action_pattern_candidate',ret['candidate_id'],ret['availability_time'])])
        for spring_def,sign_def,hyp_def,direction,prior_def,rehyp in [('wyckoff_spring_candidate','wyckoff_sign_of_strength','wyckoff_accumulation_hypothesis','bullish','dow_advancing_structure','wyckoff_reaccumulation_hypothesis'),('wyckoff_upthrust_candidate','wyckoff_sign_of_weakness','wyckoff_distribution_hypothesis','bearish','dow_declining_structure','wyckoff_redistribution_hypothesis')]:
            for spring in self.out.execute('SELECT * FROM school_interpretation WHERE definition_id=? ORDER BY availability_time',(spring_def,)).fetchall():
                sign=self.out.execute('SELECT * FROM school_interpretation WHERE definition_id=? AND symbol=? AND timeframe=? AND availability_time>? ORDER BY availability_time LIMIT 1',(sign_def,spring['symbol'],spring['timeframe'],spring['availability_time'])).fetchone()
                if not sign:continue
                hid=self._write_hypothesis(hyp_def,symbol=spring['symbol'],timeframe=spring['timeframe'],direction=direction,event_time=int(spring['event_time']),confirmation_time=int(sign['confirmation_time']),availability_time=max_time(spring['availability_time'],sign['availability_time']),upstream_refs=[self._ref('group8','school_interpretation',spring['interpretation_id'],spring['availability_time']),self._ref('group8','school_interpretation',sign['interpretation_id'],sign['availability_time'])])
                prior=self.out.execute('SELECT * FROM school_interpretation WHERE definition_id=? AND symbol=? AND timeframe=? AND availability_time<? ORDER BY availability_time DESC LIMIT 1',(prior_def,spring['symbol'],spring['timeframe'],spring['availability_time'])).fetchone()
                if prior:self._write_hypothesis(rehyp,symbol=spring['symbol'],timeframe=spring['timeframe'],direction=direction,event_time=int(spring['event_time']),confirmation_time=int(sign['confirmation_time']),availability_time=max_time(spring['availability_time'],sign['availability_time'],prior['availability_time']),upstream_refs=[self._ref('group8','narrative_hypothesis',hid,max_time(spring['availability_time'],sign['availability_time'])),self._ref('group8','school_interpretation',prior['interpretation_id'],prior['availability_time'])])
        self.out.commit()

    def run_derived(self)->dict[str,Any]:
        self.process_exhaustion_from_catalog();self.process_wyckoff_pa7_dependent()
        counts={'interpretations':{d:int(self.out.execute('SELECT COUNT(*) FROM school_interpretation WHERE definition_id=?',(d,)).fetchone()[0]) for d in sorted(DERIVED_INTERPRETATIONS)},'hypotheses':{d:int(self.out.execute('SELECT COUNT(*) FROM narrative_hypothesis WHERE definition_id=?',(d,)).fetchone()[0]) for d in sorted(DERIVED_HYPOTHESES)}}
        return {'format_version':1,'status':'PASS','year':self.year,'physical_role':'PA7_DEPENDENT_DERIVED','definition_coverage':counts,'free_only':True,'paid_runner_allowed':False,'paid_service_allowed':False,'oos_2024_accessed':self.year==2024}

def main()->int:
    p=argparse.ArgumentParser();p.add_argument('--staging-db',type=Path,required=True);p.add_argument('--working-db',type=Path,required=True);p.add_argument('--pa7-catalog',type=Path,required=True);p.add_argument('--artifacts-root',type=Path,required=True);p.add_argument('--year',type=int,required=True);p.add_argument('--symbol');p.add_argument('--report',type=Path);a=p.parse_args()
    if a.year==2024:
        s=json.loads((a.artifacts_root/'STATUS.json').read_text())
        if s.get('annual_execution_2024_authorized') is not True:raise SystemExit('2024 OOS is forbidden')
    e=PA7DerivedEngine(staging_db=a.staging_db,output_db=a.working_db,pa7_catalog=a.pa7_catalog,artifacts_root=a.artifacts_root,year=a.year,symbol=a.symbol)
    try:r=e.run_derived()
    finally:e.close()
    if a.report:a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(r,indent=2,sort_keys=True)+'\n')
    print(json.dumps(r,indent=2,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
