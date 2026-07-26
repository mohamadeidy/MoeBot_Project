#!/usr/bin/env python3
from __future__ import annotations
import json, sqlite3, tempfile, unittest
from pathlib import Path

from moebot_group8_engine_v0_8_0 import Group8Engine, ENGINE_VERSION, SCHEMA_VERSION, CONFIG_ID, EXPECTED_LOGICAL_LINEAGE

ART=Path(__file__).resolve().parents[1] if (Path(__file__).resolve().parents[1]/'FROZEN_CONFIG.json').is_file() else Path('/mnt/data/g8freeze')
ADAPTER=json.loads((ART/'UPSTREAM_ADAPTER_MAP.json').read_text())
TEXT_HINTS={'id','symbol','timeframe','timeframe_code','parent_timeframe_code','direction','direction_code','volatility_code','phase_code','stable_label_code','layer','event_type','status','status_after','role_after','from_status','to_status','reason','break_kind','outcome','swing_type','relation','pool_class','side','active_bias','sequence_bias','draw_side','resolution','variant_type','classification','separation_reason','leg_kind','origin_label','initial_classification','validation_type','result','fill_state','directional_validity','source_group','subject_type','source_type','relation_type','definition_id','definition_version','range_policy','definition_json','definition_hash','zone_label','evidence_type','freshness','inversion_status','direction_before','direction_after','child_type','parent_type','direction_alignment','creation_hash','record_hash','event_hash','state_hash','feature_hash','candidate_hash','match_hash','pool_hash','void_hash','inducement_hash','draw_hash','transition_hash','evidence_hash','summary_hash','relation_hash','source_bar_hash','content_hash','parent_event_id','source_event_id','source_pool_id','target_pool_id','resolution_event_id','selected_pool_id','nearest_buy_pool_id','nearest_sell_pool_id','source_swing_id','source_zone_id','source_leg_id','candidate_id','match_id','zone_id','pool_id','leg_id','fvg_id','bpr_id','inversion_id','variant_id','transition_id','validation_id','evidence_id','state_id','event_id','swing_id','parent_zone_id','group2_state_id','group3_state_id','associated_leg_id','associated_group3_event_id','associated_group5_event_id','bullish_fvg_id','bearish_fvg_id','original_fvg_id','child_id','parent_id'}
REAL_HINTS={'open','high','low','close','lower','upper','anchor_price','origin_atr','atr','confidence','strength_score','level_price','depth_atr','penetration_ratio','arrival_speed','arrival_efficiency','current_strength','origin_strength','max_penetration','max_confluence','width','size_atr','ce','formation_quality','max_consumption','max_fill_ratio','max_fill','width_atr','overlap_ratio'}

def ctype(c):
    if c in REAL_HINTS or any(x in c for x in ('ratio','price','strength','confidence','penetration','atr','width','lower','upper','open','high','low','close','ce')):return 'REAL'
    if c in TEXT_HINTS or c.endswith('_hash') or c.endswith('_id') or 'json' in c or 'direction' in c or 'status' in c or 'type' in c or 'label' in c or 'role' in c or 'class' in c or 'bias' in c or 'state' in c or 'reason' in c or 'relation' in c or 'kind' in c:return 'TEXT'
    return 'INTEGER'

def empty_row(group,table):
    return {c:None for c in ADAPTER['adapters'][group][table]['required_columns']}

def insert(con,table,row):
    cols=list(row);con.execute(f'INSERT INTO "{table}" ({",".join(cols)}) VALUES ({",".join("?" for _ in cols)})',[row[c] for c in cols])

def make_stage(path:Path):
    con=sqlite3.connect(path);con.execute('CREATE TABLE stage_manifest(key TEXT PRIMARY KEY,value TEXT NOT NULL)');con.execute('CREATE TABLE staging_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
    identities={g:{'filename':f'{g}.sqlite','size_bytes':1,'sha256':(g+'0'*64)[:64],'engine_version':'x','schema_version':'x','config_id':'x'} for g in ['source','group2','group3','group4','group5','group6','group7']}
    vals={'status':'PASS','year':'2023','engine_version':ENGINE_VERSION,'schema_version':SCHEMA_VERSION,'config_id':CONFIG_ID,'logical_dependency_lineage_id':EXPECTED_LOGICAL_LINEAGE,'adapter_map_hash':ADAPTER['adapter_map_hash'],'symbol':'XAUUSD_','database_identities_json':json.dumps(identities)};con.executemany('INSERT INTO stage_manifest VALUES (?,?)',vals.items());con.execute("INSERT INTO staging_metadata VALUES('verified_tick_size:XAUUSD_','0.1')")
    for g,tables in ADAPTER['adapters'].items():
        for name,rec in tables.items():con.execute(f'CREATE TABLE "{g}__{name}" ({", ".join(f"\"{c}\" {ctype(c)}" for c in rec["required_columns"])})')
    for code,tf,sec,parent in [('M15','M15',900,'H1'),('H1','H1',3600,None)]:
        r=empty_row('group2','timeframe_dictionary');r.update(timeframe_code=code,timeframe=tf,seconds=sec,parent_timeframe_code=parent);insert(con,'group2__timeframe_dictionary',r)
    bars=[(100,101,99,100.2 if i%2==0 else 99.8) for i in range(14)]+[(100,102,98,100),(100.5,101,99,99.5),(99,103,97,102),(100,100.7,97,100.5),(101,104,100,103),(104,107,103.5,106.5),(106.5,108,106.2,107),(105.2,105.4,104.8,105.1),(104.5,108,103.8,104),(96,96.5,93,94),(93.8,94,92.5,93),(94.8,95.2,94.5,94.9),(95.5,96,92,95.8),(100,101,99,100.1),(100,100.2,99.8,100),(100,101,99,100.4)]
    base=1_700_000_000
    for i,(o,h,l,c) in enumerate(bars):
        ct=base+(i+1)*900;r=empty_row('source','bars');r.update(id=i+1,symbol='XAUUSD_',timeframe='M15',open_time=ct-900,close_time=ct,available_at=ct,open=o,high=h,low=l,close=c,tick_volume=100+i,content_hash=f'bar{i+1}');insert(con,'source__bars',r)
    for i in range(8):
        ct=base+(i+1)*3600;r=empty_row('source','bars');r.update(id=100+i,symbol='XAUUSD_',timeframe='H1',open_time=ct-3600,close_time=ct,available_at=ct,open=100,high=102,low=98,close=101 if i%2==0 else 99,tick_volume=500,content_hash=f'h1{i}');insert(con,'source__bars',r)
    for sid,tf,layer,ct,ab,sb,bid in [('st_bear_ext','M15','external',base+4*900,'bearish','bearish',4),('st_bull_int','M15','internal',base+5*900,'bullish','bullish',5),('st_ind_ext','M15','external',base+14*900,'unknown','transition',14),('st_h1_bull','H1','external',base+3*3600,'bullish','bullish',102)]:
        r=empty_row('group3','structure_states');r.update(state_id=sid,symbol='XAUUSD_',timeframe=tf,bar_id=bid,open_time=ct-(900 if tf=='M15' else 3600),close_time=ct,layer=layer,sequence_bias=sb,active_bias=ab,leg='impulse',protected_high_id='ph',protected_low_id='pl',last_event_type='BOS',last_event_id='be0',atr=2,state_hash=sid+'hash');insert(con,'group3__structure_states',r)
    for eid,et,d,cand,res,bid in [('be_bos_up','BOS','up',base+18*900,base+19*900,19),('be_mss_up','MSS','up',base+15*900,base+16*900,16),('be_choch_dn','CHOCH','down',base+21*900,base+22*900,22)]:
        r=empty_row('group3','break_events');r.update(event_id=eid,symbol='XAUUSD_',timeframe='M15',layer='internal',candidate_id=eid+'c',event_type=et,direction=d,break_kind='continuation' if et=='BOS' else 'reversal',level_price=105 if d=='up' else 95,level_swing_id='sw',candidate_time=cand,resolved_time=res,candidate_bar_id=bid-1,resolved_bar_id=bid,strength_score=1,strong_break=1,outcome='accepted',feature_hash=eid+'hash');insert(con,'group3__break_events',r)
    for i in range(2):
        r=empty_row('group3','swings');r.update(swing_id=f'sw{i}',symbol='XAUUSD_',timeframe='M15',layer='external',swing_type='high' if i==0 else 'low',extreme_time=base+(6+i)*900,confirmation_time=base+(7+i)*900,available_at=base+(7+i)*900,price=105 if i==0 else 95,atr=2,relation='INITIAL',source_bar_id=7+i,event_hash=f'swh{i}');insert(con,'group3__swings',r)
    for zid,lo,hi,role in [('zlow',94,95,'support'),('zhigh',105,106,'resistance')]:
        r=empty_row('group4','zones');r.update(zone_id=zid,symbol='XAUUSD_',timeframe='M15',source_timeframe='M15',zone_class='reference',initial_role=role,current_role=role,layer='external',origin_time=base+2*900,available_at=base+3*900,expires_at=None,lower=lo,upper=hi,origin_atr=2,origin_strength=1,status='active',touch_count=0,max_penetration=0,current_strength=1,broken_direction=None,source_swing_id='sw0',source_event_id='be0',source_bar_id=2,feature_hash=zid+'hash');insert(con,'group4__zones',r)
    for pid,anchor,side in [('plow',95,'sell_side'),('phigh',105,'buy_side')]:
        r=empty_row('group5','liquidity_pools');r.update(pool_id=pid,symbol='XAUUSD_',timeframe='M15',pool_class='equal_level',side=side,layer='external',origin_time=base+8*900,available_at=base+9*900,expires_at=None,anchor_price=anchor,lower=anchor-.1,upper=anchor+.1,origin_atr=2,status='active',first_sweep_time=None,first_event_id=None,source_swing_id='sw0',source_zone_id='zlow' if pid=='plow' else 'zhigh',pool_hash=pid+'hash');insert(con,'group5__liquidity_pools',r)
    for eid,pid,side,cand,res in [('liq_spring','plow','sell_side',base+15*900,base+16*900),('liq_upthrust','phigh','buy_side',base+16*900,base+17*900)]:
        r=empty_row('group5','liquidity_events');r.update(event_id=eid,pool_id=pid,timeframe='M15',side=side,event_type='sweep',candidate_time=cand,resolved_time=res,start_bar_id=15,resolved_bar_id=16,duration_bars=1,depth_atr=.2,reclaimed=1,same_bar=0,closed_beyond=0,is_sweep=1,is_liquidity_grab=0,is_stop_run=1,is_false_breakout=1,resolution='reclaimed',parent_event_id=None,event_hash=eid+'hash');insert(con,'group5__liquidity_events',r)
    r=empty_row('group5','draw_states');r.update(draw_id='draw1',timeframe='M15',bar_id=18,open_time=base+17*900,close_time=base+18*900,active_bias='bullish',draw_side='buy_side',selected_pool_id='phigh',nearest_buy_pool_id='phigh',nearest_sell_pool_id='plow',confidence=.8,draw_hash='drawhash');insert(con,'group5__draw_states',r)
    for lid,d,bid,av in [('leg_bear_pull','bearish',17,base+17*900),('leg_bull','bullish',19,base+19*900),('leg_bear','bearish',23,base+23*900)]:
        r=empty_row('group6','displacement_legs');r.update(leg_id=lid,timeframe='M15',leg_kind='single',direction=d,start_bar_id=bid-1,end_bar_id=bid,start_time=av-900,end_time=av,confirmation_time=av,availability_time=av,origin_bar_id=bid-1,origin_window_start=bid-2,origin_window_end=bid-1,body_lower=99,body_upper=101,wick_lower=98,wick_upper=102,full_lower=98,full_upper=102,last_opposing_bar_id=bid-1,origin_label='last_opposing',initial_classification='validated',uncertain=0,record_hash=lid+'hash');insert(con,'group6__displacement_legs',r)
        v=empty_row('group6','displacement_validation_events');v.update(validation_id='v_'+lid,leg_id=lid,fvg_id='fvg1' if lid=='leg_bull' else None,confirmation_bar_id=bid,confirmation_time=av,availability_time=av,validation_type='validated',result='PASS',record_hash='v'+lid);insert(con,'group6__displacement_validation_events',v)
    r=empty_row('group6','fvg_events');r.update(fvg_id='fvg1',timeframe='M15',direction='bullish',creation_time=base+18*900,confirmation_time=base+19*900,availability_time=base+19*900,lower=102,upper=103,ce=102.5,size_atr=.5,associated_leg_id='leg_bull',associated_group3_event_id='be_bos_up',associated_group5_event_id='liq_spring',group2_state_id=None,group3_state_id='st_bull_int',clean_displacement=1,formation_quality=1,record_hash='fvg1hash');insert(con,'group6__fvg_events',r)
    r=empty_row('group6','fvg_state_transitions');r.update(transition_id='fvgtr1',fvg_id='fvg1',transition_ordinal=1,bar_id=21,transition_time=base+21*900,event_type='touch',fill_state='partial',directional_validity='valid',max_penetration=.2,record_hash='trhash');insert(con,'group6__fvg_state_transitions',r)
    r=empty_row('group6','fvg_lifecycle_summary');r.update(fvg_id='fvg1',fill_state='partial',directional_validity='valid',max_penetration=.2,first_touch_time=base+21*900,ce_time=None,full_fill_time=None,traverse_time=None,visit_count=1,record_hash='sumhash');insert(con,'group6__fvg_lifecycle_summary',r)
    r=empty_row('group6','group6_evidence');r.update(evidence_id='g6ev1',subject_type='displacement_leg',subject_id='leg_bull',source_group='group5',source_id='liq_spring',relation_type='post_sweep_displacement',source_timeframe='M15',availability_time=base+19*900,details_json='{}',record_hash='g6evhash');insert(con,'group6__group6_evidence',r)
    r=empty_row('group6','imbalance_variants');r.update(variant_id='imb1',timeframe='M15',variant_type='imbalance',direction='bullish',start_bar_id=18,end_bar_id=19,availability_time=base+19*900,lower=101,upper=102,size_atr=.5,classification='clean',separation_reason='',record_hash='imbhash');insert(con,'group6__imbalance_variants',r)
    r=empty_row('group6','liquidity_voids');r.update(void_id='void1',timeframe='M15',direction='bullish',start_time=base+18*900,end_time=base+19*900,availability_time=base+19*900,lower=103,upper=104,width_atr=.5,member_count=2,state='active',max_fill=0,record_hash='voidhash');insert(con,'group6__liquidity_voids',r)
    r=empty_row('group6','bpr_relations');r.update(bpr_id='bpr1',bullish_fvg_id='fvg1',bearish_fvg_id='fvgX',timeframe='M15',lower=99,upper=100,width=1,creation_time=base+19*900,availability_time=base+19*900,second_fvg_direction='bearish',group2_state_id=None,group3_state_id='st_ind_ext',state='active',max_consumption=0,record_hash='bprhash');insert(con,'group6__bpr_relations',r)
    r=empty_row('group6','inversion_fvg_relations');r.update(inversion_id='inv1',original_fvg_id='fvg1',confirmation_bar_id=22,confirmation_time=base+22*900,availability_time=base+22*900,direction_before='bullish',direction_after='bearish',close_through_evidence='yes',inversion_status='confirmed',first_retest_time=None,first_retest_bar_id=None,record_hash='invhash');insert(con,'group6__inversion_fvg_relations',r)
    r=empty_row('group6','mtf_imbalance_relations');r.update(relation_id='mtfg6',child_type='fvg',child_id='fvg1',child_timeframe='M15',parent_type='fvg',parent_id='fvgH1',parent_timeframe='H1',relation_type='contained',direction_alignment='same',overlap_ratio=.5,availability_time=base+22*900,record_hash='mtfhash');insert(con,'group6__mtf_imbalance_relations',r)
    r=empty_row('group7','definition_registry');r.update(definition_id='strict_order_block',definition_version='1',derived=0,range_policy='full',invalidation_closes=1,definition_json='{}',definition_hash='dhash');insert(con,'group7__definition_registry',r)
    r=empty_row('group7','definition_candidates');r.update(candidate_id='g7c',definition_id='strict_order_block',source_leg_id='leg_bull',candidate_time=base+18*900,availability_time=base+19*900,lower=100,upper=101,source_bar_id=18,intrinsic_pass=1,candidate_hash='g7chash');insert(con,'group7__definition_candidates',r)
    r=empty_row('group7','definition_matches');r.update(match_id='g7m',candidate_id='g7c',definition_id='strict_order_block',source_leg_id='leg_bull',match_time=base+19*900,availability_time=base+19*900,evidence_availability_max=base+19*900,evidence_ids_json='["g7e"]',match_hash='g7mhash');insert(con,'group7__definition_matches',r)
    r=empty_row('group7','institutional_zones');r.update(zone_id='g7z',definition_id='strict_order_block',timeframe='M15',direction='bullish',zone_label='strict_order_block',lower=100,upper=101,event_time=base+18*900,confirmation_time=base+19*900,availability_time=base+19*900,source_leg_id='leg_bull',candidate_id='g7c',match_id='g7m',origin_bar_id=18,source_bar_id=18,parent_zone_id=None,creation_hash='g7zhash');insert(con,'group7__institutional_zones',r)
    r=empty_row('group7','zone_evidence');r.update(evidence_id='g7e',zone_id='g7z',evidence_type='delivery',source_group='group6',source_id='leg_bull',relation_type='source_leg',availability_time=base+19*900,evidence_hash='g7ehash');insert(con,'group7__zone_evidence',r)
    r=empty_row('group7','zone_lifecycle_summary');r.update(zone_id='g7z',status='active',freshness='fresh',visit_count=0,mitigation_count=0,max_penetration=0,first_touch_time=None,invalidated_time=None,summary_hash='g7sum');insert(con,'group7__zone_lifecycle_summary',r)
    con.commit();con.close()

class Group8Tests(unittest.TestCase):
    def run_engine(self):
        td=tempfile.TemporaryDirectory();root=Path(td.name);stage=root/'stage.sqlite';out=root/'out.sqlite';make_stage(stage);eng=Group8Engine(staging_db=stage,output_db=out,artifacts_root=ART,year=2023,symbol='XAUUSD_');report=eng.run();eng.close();return td,stage,out,report
    def test_frozen_evaluator_registry_exact_45(self):
        frozen=set(json.loads((ART/'01_DEFINITION_REGISTRY.json').read_text())['definitions']);self.assertEqual(frozen,set(Group8Engine.evaluator_registry()));self.assertEqual(len(frozen),45)
    def test_full_synthetic_pipeline_and_causality(self):
        td,stage,out,report=self.run_engine()
        try:
            self.assertEqual(report['status'],'PASS',report['failures']);self.assertEqual(len(report['definition_coverage']),45);self.assertTrue(all(v>0 for v in report['definition_coverage'].values()),[k for k,v in report['definition_coverage'].items() if v==0]);con=sqlite3.connect(out)
            self.assertEqual(con.execute('PRAGMA foreign_key_check').fetchall(),[]);self.assertEqual(con.execute("SELECT COUNT(*) FROM price_action_pattern_candidate WHERE availability_time<confirmation_time OR confirmation_time<event_time").fetchone()[0],0);self.assertEqual(con.execute("SELECT COUNT(*) FROM school_interpretation WHERE availability_time<confirmation_time OR confirmation_time<event_time").fetchone()[0],0);con.close()
        finally:td.cleanup()
    def test_idempotence_and_conflicting_duplicate_rejection(self):
        td,stage,out,report=self.run_engine()
        try:
            con=sqlite3.connect(out);before={t:con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in ['price_action_pattern_candidate','school_interpretation','narrative_hypothesis','evidence_chain']};con.close();eng=Group8Engine(staging_db=stage,output_db=out,artifacts_root=ART,year=2023,symbol='XAUUSD_');r2=eng.run();eng.close();self.assertEqual(r2['status'],'PASS',r2['failures']);con=sqlite3.connect(out);after={t:con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in before};con.close();self.assertEqual(before,after)
        finally:td.cleanup()
    def test_read_only_upstream_and_immutable_creation(self):
        td,stage,out,report=self.run_engine()
        try:
            eng=Group8Engine(staging_db=stage,output_db=out,artifacts_root=ART,year=2023,symbol='XAUUSD_')
            with self.assertRaises(sqlite3.OperationalError):eng.input.execute("UPDATE source__bars SET close=0 WHERE id=1")
            eng.close();con=sqlite3.connect(out);cid=con.execute("SELECT candidate_id FROM price_action_pattern_candidate LIMIT 1").fetchone()[0]
            with self.assertRaises(sqlite3.IntegrityError):con.execute("UPDATE price_action_pattern_candidate SET direction='neutral' WHERE candidate_id=?",(cid,))
            con.close()
        finally:td.cleanup()
    def test_conflicting_duplicate_rejected(self):
        td=tempfile.TemporaryDirectory();root=Path(td.name);stage=root/'stage.sqlite';out=root/'out.sqlite';make_stage(stage)
        try:
            eng=Group8Engine(staging_db=stage,output_db=out,artifacts_root=ART,year=2023,symbol='XAUUSD_')
            with self.assertRaises(Exception):eng._insert_immutable('school_registry','school_id','school_classical_price_action_v1',{'school_id':'school_classical_price_action_v1','school_version':'1.0.0','school_name':'changed','scope_json':'{}','prohibitions_json':'{}','school_hash':'BAD'},hash_column='school_hash',expected_hash='BAD')
            eng.close()
        finally:td.cleanup()
    @staticmethod
    def _ids_by_table(db):
        con=sqlite3.connect(db);out={}
        for table,idc in [('price_action_pattern_candidate','candidate_id'),('school_interpretation','interpretation_id'),('narrative_hypothesis','hypothesis_id'),('shared_evidence','shared_evidence_id'),('conflicting_evidence','conflict_id'),('multi_timeframe_context_relation','relation_id')]:out[table]={r[0] for r in con.execute(f'SELECT {idc} FROM {table}')}
        con.close();return out
    def test_restart_parity(self):
        td=tempfile.TemporaryDirectory();root=Path(td.name);stage=root/'stage.sqlite';partial=root/'partial.sqlite';fresh=root/'fresh.sqlite';make_stage(stage)
        try:
            e=Group8Engine(staging_db=stage,output_db=partial,artifacts_root=ART,year=2023,symbol='XAUUSD_');e.load_bars();e.process_base_price_action();e.process_dow();e.close();e=Group8Engine(staging_db=stage,output_db=partial,artifacts_root=ART,year=2023,symbol='XAUUSD_');r=e.run();e.close();self.assertEqual(r['status'],'PASS',r['failures']);e=Group8Engine(staging_db=stage,output_db=fresh,artifacts_root=ART,year=2023,symbol='XAUUSD_');r=e.run();e.close();self.assertEqual(r['status'],'PASS',r['failures']);self.assertEqual(self._ids_by_table(partial),self._ids_by_table(fresh))
        finally:td.cleanup()
    def test_prefix_future_append_stability(self):
        td=tempfile.TemporaryDirectory();root=Path(td.name);fullstage=root/'fullstage.sqlite';prefixstage=root/'prefixstage.sqlite';fullout=root/'full.sqlite';prefixout=root/'prefix.sqlite';make_stage(fullstage)
        try:
            import shutil;shutil.copy2(fullstage,prefixstage);cutoff=1_700_000_000+18*900;con=sqlite3.connect(prefixstage);time_priority=['availability_time','available_at','resolved_time','close_time','transition_time','confirmation_time','match_time','candidate_time','origin_time']
            for table, in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%__%'").fetchall():
                cols={r[1] for r in con.execute(f'PRAGMA table_info("{table}")')};tc=next((x for x in time_priority if x in cols),None)
                if tc:con.execute(f'DELETE FROM "{table}" WHERE "{tc}" IS NOT NULL AND "{tc}">?',(cutoff,))
            con.commit();con.close()
            for st,out in [(fullstage,fullout),(prefixstage,prefixout)]:e=Group8Engine(staging_db=st,output_db=out,artifacts_root=ART,year=2023,symbol='XAUUSD_');r=e.run();e.close();self.assertEqual(r['status'],'PASS',r['failures'])
            cf=sqlite3.connect(fullout);cp=sqlite3.connect(prefixout)
            for table,idc in [('price_action_pattern_candidate','candidate_id'),('school_interpretation','interpretation_id'),('narrative_hypothesis','hypothesis_id')]:self.assertEqual({r[0] for r in cf.execute(f'SELECT {idc} FROM {table} WHERE availability_time<=?',(cutoff,))},{r[0] for r in cp.execute(f'SELECT {idc} FROM {table} WHERE availability_time<=?',(cutoff,))},table)
            cf.close();cp.close()
        finally:td.cleanup()
    def test_year_end_zone_status_not_used_historically(self):
        td=tempfile.TemporaryDirectory();root=Path(td.name);stage=root/'stage.sqlite';out=root/'out.sqlite';make_stage(stage)
        try:
            con=sqlite3.connect(stage);con.execute("UPDATE group4__zones SET status='invalidated' WHERE zone_id='zlow'");con.commit();con.close();e=Group8Engine(staging_db=stage,output_db=out,artifacts_root=ART,year=2023,symbol='XAUUSD_');r=e.run();e.close();self.assertEqual(r['status'],'PASS',r['failures']);con=sqlite3.connect(out);n=con.execute("SELECT COUNT(*) FROM price_action_pattern_candidate WHERE definition_id='pa_bounded_range_context'").fetchone()[0];con.close();self.assertGreater(n,0)
        finally:td.cleanup()
    def test_positive_price_scale_invariance(self):
        td=tempfile.TemporaryDirectory();root=Path(td.name);a=root/'a.sqlite';b=root/'b.sqlite';oa=root/'oa.sqlite';ob=root/'ob.sqlite';make_stage(a)
        try:
            import shutil;shutil.copy2(a,b);con=sqlite3.connect(b);scale=10.;scale_cols={'open','high','low','close','level_price','price','atr','origin_atr','anchor_price','lower','upper','body_lower','body_upper','wick_lower','wick_upper','full_lower','full_upper','ce','width','size_atr','width_atr','depth_atr'}
            for table, in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%__%'").fetchall():
                cols={r[1] for r in con.execute(f'PRAGMA table_info("{table}")')}
                for c in sorted(cols&scale_cols):con.execute(f'UPDATE "{table}" SET "{c}"="{c}"*? WHERE "{c}" IS NOT NULL',(scale,))
            con.execute("UPDATE staging_metadata SET value=CAST(CAST(value AS REAL)*? AS TEXT) WHERE key LIKE 'verified_%'",(scale,));con.commit();con.close();reports=[]
            for st,out in [(a,oa),(b,ob)]:e=Group8Engine(staging_db=st,output_db=out,artifacts_root=ART,year=2023,symbol='XAUUSD_');r=e.run();e.close();self.assertEqual(r['status'],'PASS',r['failures']);reports.append(r)
            self.assertEqual({k:(v>0) for k,v in reports[0]['definition_coverage'].items()},{k:(v>0) for k,v in reports[1]['definition_coverage'].items()})
        finally:td.cleanup()
    def test_threshold_boundaries(self):
        cfg=json.loads((ART/'FROZEN_CONFIG.json').read_text())['pattern_thresholds'];self.assertEqual(cfg['doji_strict_body_to_range_max'],0.1);self.assertEqual(cfg['doji_broad_body_to_range_max'],0.2);self.assertEqual(cfg['pin_dominant_wick_to_range_min'],0.6);self.assertEqual(cfg['pin_body_to_range_max'],0.3);self.assertEqual(cfg['pin_opposite_wick_to_range_max'],0.15);self.assertEqual(cfg['rejection_wick_to_range_min'],0.5);self.assertEqual(cfg['rejection_close_outer_fraction'],0.25);self.assertEqual(cfg['atr_buffer_breakout_fraction'],0.1)

if __name__=='__main__':unittest.main(verbosity=2)
