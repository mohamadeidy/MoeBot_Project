#!/usr/bin/env python3
"""FREE-ONLY Group 8 annual core executor.

The annual core owns definitions that do not require PA7 breakout-chain rows.  PA7
and its dependent derived definitions are materialized separately under the frozen
lossless sharded storage contract.  This module changes physical execution only;
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

    def run_core(self) -> dict[str, Any]:
        stages = [
            ('load_bars', self.load_bars),
            ('base_price_action', self.process_base_price_action),
            ('dow', self.process_dow),
            ('bounded_ranges', self.process_bounded_ranges),
            ('context_rejections_fast', self.process_context_rejections_fast),
            ('structural_narratives_fast', self.process_structural_narratives_fast),
            ('wyckoff_core', self.process_wyckoff),
            ('ict_core', self.process_ict),
        ]
        for stage_name, fn in stages:
            fn()
            checkpoint(self, stage_name)

        # Fail closed if a PA7 or PA7-dependent definition leaked into core.
        unexpected = []
        for table in ('price_action_pattern_candidate','school_interpretation','narrative_hypothesis'):
            rows = self.out.execute(f'SELECT DISTINCT definition_id FROM {table} ORDER BY definition_id').fetchall()
            for row in rows:
                definition = str(row[0])
                allowed = (CORE_PATTERN_DEFINITIONS if table == 'price_action_pattern_candidate'
                           else CORE_INTERPRETATION_DEFINITIONS if table == 'school_interpretation'
                           else CORE_HYPOTHESIS_DEFINITIONS)
                if definition not in allowed:
                    unexpected.append(f'{table}:{definition}')
        if unexpected:
            raise RuntimeError(f'annual core definition leakage: {unexpected}')

        report = {
            'format_version': 1,
            'status': 'PASS',
            'year': self.year,
            'physical_role': 'ANNUAL_CORE_NON_PA7',
            'free_only': True,
            'paid_runner_allowed': False,
            'paid_service_allowed': False,
            'oos_2024_accessed': self.year == 2024,
            'definition_coverage': {
                'patterns': {d: int(self.out.execute('SELECT COUNT(*) FROM price_action_pattern_candidate WHERE definition_id=?',(d,)).fetchone()[0]) for d in sorted(CORE_PATTERN_DEFINITIONS)},
                'interpretations': {d: int(self.out.execute('SELECT COUNT(*) FROM school_interpretation WHERE definition_id=?',(d,)).fetchone()[0]) for d in sorted(CORE_INTERPRETATION_DEFINITIONS)},
                'hypotheses': {d: int(self.out.execute('SELECT COUNT(*) FROM narrative_hypothesis WHERE definition_id=?',(d,)).fetchone()[0]) for d in sorted(CORE_HYPOTHESIS_DEFINITIONS)},
            },
            'deferred': {
                'pa7_chain': sorted(PA7_CHAIN_DEFINITIONS),
                'pa7_dependent_derived': sorted(PA7_DERIVED_DEFINITIONS),
                'cross_school_mtf': True,
                'global_lifecycle_and_invalidations': True,
            },
        }
        return report


def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument('--staging-db',type=Path,required=True)
    p.add_argument('--output-db',type=Path,required=True)
    p.add_argument('--artifacts-root',type=Path,required=True)
    p.add_argument('--year',type=int,required=True)
    p.add_argument('--symbol')
    p.add_argument('--report',type=Path)
    a=p.parse_args()
    if a.year == 2024:
        status=json.loads((a.artifacts_root/'STATUS.json').read_text())
        if status.get('annual_execution_2024_authorized') is not True:
            raise SystemExit('2024 OOS is forbidden')
    e=AnnualCoreEngine(staging_db=a.staging_db,output_db=a.output_db,artifacts_root=a.artifacts_root,year=a.year,symbol=a.symbol)
    try:
        report=e.run_core()
    finally:
        e.close()
    if a.report:
        a.report.parent.mkdir(parents=True,exist_ok=True)
        a.report.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps(report,indent=2,sort_keys=True))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
