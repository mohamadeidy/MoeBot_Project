#!/usr/bin/env python3
"""FREE-ONLY Group 8 annual core executor.

The annual core owns definitions that do not require PA7 breakout-chain rows. PA7
and its dependent derived definitions are materialized separately under the frozen
lossless sharded storage contract. This module changes physical execution only;
all logical writes are delegated to the frozen Group8 engine/verified fast paths.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from group8_context_rejection_fastpath import IndexedContextRejectionEngine
from group8_structural_narrative_fastpath import IndexedStructuralNarrativeEngine
from group8_postprocess_v0_8_0 import checkpoint
from moebot_group8_engine_v0_8_0 import max_time

CORE_PATTERN_DEFINITIONS = {
    'pa_candle_anatomy','pa_inside_bar_edge','pa_inside_bar_strict','pa_outside_bar_edge',
    'pa_outside_bar_strict','pa_body_engulfing','pa_directional_body_engulfing',
    'pa_full_range_engulfing','pa_doji_strict','pa_doji_broad','pa_pin_bar_like',
    'pa_rejection_close','pa_bounded_range_context','pa_context_linked_rejection',
}
CORE_INTERPRETATION_DEFINITIONS = {
    'dow_advancing_structure','dow_declining_structure','dow_indeterminate_structure',
    'dow_bullish_transition','dow_bearish_transition','dow_protected_pullback',
    'wyckoff_range_context','wyckoff_spring_candidate','wyckoff_upthrust_candidate',
    'ict_liquidity_sweep_displacement','ict_mss_fvg_delivery','ict_premium_discount_context',
    'ict_return_to_imbalance','ict_block_delivery_context','ict_draw_on_liquidity_context',
}
CORE_HYPOTHESIS_DEFINITIONS = {'pa_structural_pullback','pa_continuation_after_pullback'}
PA7_CHAIN_DEFINITIONS = {'pa_breakout_exact','pa_breakout_point_buffer','pa_breakout_atr_buffer','pa_failed_breakout','pa_retest'}
PA7_DERIVED_DEFINITIONS = {
    'pa_exhaustion_failed_breakout','wyckoff_sign_of_strength','wyckoff_sign_of_weakness',
    'wyckoff_last_point_of_support','wyckoff_last_point_of_supply',
    'wyckoff_accumulation_hypothesis','wyckoff_distribution_hypothesis',
    'wyckoff_reaccumulation_hypothesis','wyckoff_redistribution_hypothesis',
}


class AnnualCoreEngine(IndexedContextRejectionEngine, IndexedStructuralNarrativeEngine):
    """Exact non-PA7 annual core using already-proven physical fast paths."""

    def process_wyckoff_core(self) -> None:
        """Frozen Wyckoff prefix only: range context + spring/upthrust.

        The remaining frozen `process_wyckoff` loops require PA7 breakout/retest
        rows. Those rows are intentionally absent from Annual Core and are produced
        later by the exact catalog-driven PA7 derived layer. Running those loops in
        Core can only do expensive work and emit nothing.
        """
        ranges=self.out.execute("SELECT * FROM price_action_pattern_candidate WHERE definition_id='pa_bounded_range_context'").fetchall()
        for rg in ranges:
            feats=json.loads(rg['features_json']);layer=feats.get('layer')
            dows=self.out.execute("SELECT * FROM school_interpretation WHERE definition_id='dow_indeterminate_structure' AND symbol=? AND timeframe=? AND availability_time<=?",(rg['symbol'],rg['timeframe'],rg['availability_time'])).fetchall()
            for dow in dows:
                drefs=json.loads(dow['upstream_refs_json']);dlayer=(drefs[0].get('details') or {}).get('layer') if drefs else None
                if layer is not None and dlayer is not None and str(layer)!=str(dlayer):continue
                iid=self._write_interpretation('wyckoff_range_context',symbol=rg['symbol'],timeframe=rg['timeframe'],direction='neutral',event_time=max_time(rg['event_time'],dow['event_time']),confirmation_time=max_time(rg['confirmation_time'],dow['confirmation_time']),availability_time=max_time(rg['availability_time'],dow['availability_time']),ambiguous=True,upstream_refs=[self._ref('group8','price_action_pattern_candidate',rg['candidate_id'],rg['availability_time']),self._ref('group8','school_interpretation',dow['interpretation_id'],dow['availability_time'])],evidence_strength={'range_context':1,'indeterminate_structure':1})
                tol_base=float(self.config['feature_parameters']['proximity_atr_fraction'])
                for ev in self.input.execute("SELECT e.*,p.symbol,p.anchor_price,p.lower,p.upper,p.available_at AS pool_available_at,p.origin_atr FROM group5__liquidity_events e JOIN group5__liquidity_pools p ON p.pool_id=e.pool_id WHERE p.symbol=? AND e.timeframe=? AND e.resolved_time IS NOT NULL AND e.resolved_time>=?",(rg['symbol'],rg['timeframe'],rg['availability_time'])):
                    if not (ev['reclaimed'] and (ev['is_sweep'] or ev['is_stop_run'] or ev['is_false_breakout'])):continue
                    event_av=int(ev['resolved_time']);pool_av=int(ev['pool_available_at']);atr=float(ev['origin_atr'] or 0);inc=self.point_increment.get(rg['symbol']);tol=max([x for x in (inc,tol_base*atr if atr else None) if x is not None],default=0.0);anchor=float(ev['anchor_price'] if ev['anchor_price'] is not None else (ev['lower']+ev['upper'])/2)
                    for definition,bound,dir_ in [('wyckoff_spring_candidate',float(rg['lower']),'bullish'),('wyckoff_upthrust_candidate',float(rg['upper']),'bearish')]:
                        if abs(anchor-bound)>tol:continue
                        self._write_interpretation(definition,symbol=rg['symbol'],timeframe=rg['timeframe'],direction=dir_,event_time=int(ev['candidate_time']),confirmation_time=event_av,availability_time=max_time(max_time(rg['availability_time'],dow['availability_time']),event_av,pool_av),upstream_refs=[self._ref('group8','school_interpretation',iid,max_time(rg['availability_time'],dow['availability_time'])),self._ref('group5','liquidity_events',ev['event_id'],event_av,event_time=ev['candidate_time'],timeframe=rg['timeframe']),self._ref('group5','liquidity_pools',ev['pool_id'],pool_av,timeframe=rg['timeframe'])],evidence_strength={'boundary_distance':abs(anchor-bound),'tolerance':tol})
        self.out.commit()

    def run_core(self) -> dict[str, Any]:
        stages = [
            ('load_bars', self.load_bars),
            ('base_price_action', self.process_base_price_action),
            ('dow', self.process_dow),
            ('bounded_ranges', self.process_bounded_ranges),
            ('context_rejections_fast', self.process_context_rejections_fast),
            ('structural_narratives_fast', self.process_structural_narratives_fast),
            ('wyckoff_core', self.process_wyckoff_core),
            ('ict_core', self.process_ict),
        ]
        for stage_name, fn in stages:
            fn();checkpoint(self,stage_name)

        unexpected=[]
        for table in ('price_action_pattern_candidate','school_interpretation','narrative_hypothesis'):
            rows=self.out.execute(f'SELECT DISTINCT definition_id FROM {table} ORDER BY definition_id').fetchall()
            for row in rows:
                definition=str(row[0]);allowed=(CORE_PATTERN_DEFINITIONS if table=='price_action_pattern_candidate' else CORE_INTERPRETATION_DEFINITIONS if table=='school_interpretation' else CORE_HYPOTHESIS_DEFINITIONS)
                if definition not in allowed:unexpected.append(f'{table}:{definition}')
        if unexpected:raise RuntimeError(f'annual core definition leakage: {unexpected}')
        return {
            'format_version':1,'status':'PASS','year':self.year,'physical_role':'ANNUAL_CORE_NON_PA7','free_only':True,
            'paid_runner_allowed':False,'paid_service_allowed':False,'oos_2024_accessed':self.year==2024,
            'definition_coverage':{
                'patterns':{d:int(self.out.execute('SELECT COUNT(*) FROM price_action_pattern_candidate WHERE definition_id=?',(d,)).fetchone()[0]) for d in sorted(CORE_PATTERN_DEFINITIONS)},
                'interpretations':{d:int(self.out.execute('SELECT COUNT(*) FROM school_interpretation WHERE definition_id=?',(d,)).fetchone()[0]) for d in sorted(CORE_INTERPRETATION_DEFINITIONS)},
                'hypotheses':{d:int(self.out.execute('SELECT COUNT(*) FROM narrative_hypothesis WHERE definition_id=?',(d,)).fetchone()[0]) for d in sorted(CORE_HYPOTHESIS_DEFINITIONS)},
            },
            'deferred':{'pa7_chain':sorted(PA7_CHAIN_DEFINITIONS),'pa7_dependent_derived':sorted(PA7_DERIVED_DEFINITIONS),'cross_school_mtf':True,'global_lifecycle_and_invalidations':True},
        }


def main()->int:
    p=argparse.ArgumentParser();p.add_argument('--staging-db',type=Path,required=True);p.add_argument('--output-db',type=Path,required=True);p.add_argument('--artifacts-root',type=Path,required=True);p.add_argument('--year',type=int,required=True);p.add_argument('--symbol');p.add_argument('--report',type=Path);a=p.parse_args()
    if a.year==2024:
        status=json.loads((a.artifacts_root/'STATUS.json').read_text())
        if status.get('annual_execution_2024_authorized') is not True:raise SystemExit('2024 OOS is forbidden')
    e=AnnualCoreEngine(staging_db=a.staging_db,output_db=a.output_db,artifacts_root=a.artifacts_root,year=a.year,symbol=a.symbol)
    try:report=e.run_core()
    finally:e.close()
    if a.report:a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps(report,indent=2,sort_keys=True));return 0

if __name__=='__main__':raise SystemExit(main())
