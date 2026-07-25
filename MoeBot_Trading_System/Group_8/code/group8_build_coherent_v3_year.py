#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, sqlite3, subprocess, sys, time
from pathlib import Path
from typing import Any

EXPECTED_G7 = {
    'engine': '898148a579532d970283b461ea446bd34045ca9dc43b53a4a59a015a5700f173',
    'audit': '3aae274d25fd3b2362b7a9b4c7ae4d799b56d463d5d7f173dd50c200162b4354',
    'visual': '4f85f362c8a00ed7f1dfc8b40b8893c7b9d0b2358782fc1bf7af62feebdc5167',
    'tests': '9a0c54b8821e0af80c2a696e06be36716e509f893e861a5ec53be1c6a17f5fb9',
    'config': 'f8347d8cf49d83a11afe96eccb74e142aafed2a8561c15865b0d81c1737825c5',
}

def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(16*1024*1024),b''): h.update(b)
    return h.hexdigest()

def ensure_visual_runtime() -> None:
    try:
        import matplotlib  # noqa: F401
    except ModuleNotFoundError:
        subprocess.run([
            sys.executable,
            '-m',
            'pip',
            'install',
            '--disable-pip-version-check',
            '--no-cache-dir',
            'matplotlib',
        ], check=True)
        import matplotlib  # noqa: F401

def summarize(db: Path, base_defs: tuple[str,...], defs: tuple[str,...]) -> dict[str,Any]:
    con=sqlite3.connect(f'file:{db.resolve()}?mode=ro&immutable=1',uri=True);con.row_factory=sqlite3.Row
    by_definition={r['definition_id']:{'evaluations':r['evaluations'],'passed_evaluations':r['passed_evaluations'],'zones':r['zones'],'fresh':r['fresh'],'tested':r['tested'],'invalidated':r['invalidated']} for r in con.execute('''
    WITH e AS (SELECT definition_id,COUNT(*) evaluations,SUM(passed=1) passed_evaluations FROM block_evaluations GROUP BY definition_id),
    z AS (SELECT z.definition_id,COUNT(*) zones,SUM(s.freshness='fresh') fresh,SUM(s.freshness='tested') tested,SUM(s.freshness='invalidated') invalidated FROM institutional_zones z JOIN zone_lifecycle_summary s USING(zone_id) GROUP BY z.definition_id)
    SELECT d.definition_id,COALESCE(e.evaluations,0) evaluations,COALESCE(e.passed_evaluations,0) passed_evaluations,COALESCE(z.zones,0) zones,COALESCE(z.fresh,0) fresh,COALESCE(z.tested,0) tested,COALESCE(z.invalidated,0) invalidated FROM definition_registry d LEFT JOIN e USING(definition_id) LEFT JOIN z USING(definition_id) ORDER BY d.definition_id''')}
    qs=','.join('?' for _ in base_defs)
    checks={
      'candidate_cardinality_errors':con.execute('SELECT COUNT(*) FROM (SELECT source_leg_id,COUNT(*) n FROM definition_candidates GROUP BY source_leg_id HAVING n!=?)',(len(base_defs),)).fetchone()[0],
      'match_before_candidate':con.execute('SELECT COUNT(*) FROM definition_matches m JOIN definition_candidates c USING(candidate_id) WHERE m.availability_time<c.availability_time').fetchone()[0],
      'match_before_evidence':con.execute('SELECT COUNT(*) FROM definition_matches WHERE availability_time<evidence_availability_max').fetchone()[0],
      'zone_before_match':con.execute('SELECT COUNT(*) FROM institutional_zones z JOIN definition_matches m USING(match_id) WHERE z.availability_time<m.availability_time').fetchone()[0],
      'base_zone_without_match':con.execute(f'SELECT COUNT(*) FROM institutional_zones WHERE definition_id IN ({qs}) AND match_id IS NULL',base_defs).fetchone()[0],
      'evidence_before_zone':con.execute('SELECT COUNT(*) FROM zone_evidence e JOIN institutional_zones z USING(zone_id) WHERE e.availability_time<z.availability_time').fetchone()[0],
      'transition_before_zone':con.execute('SELECT COUNT(*) FROM zone_state_transitions t JOIN institutional_zones z USING(zone_id) WHERE t.transition_time<z.availability_time').fetchone()[0],
      'missing_lifecycle_summary':con.execute('SELECT COUNT(*) FROM institutional_zones z LEFT JOIN zone_lifecycle_summary s USING(zone_id) WHERE s.zone_id IS NULL').fetchone()[0],
      'non_read_only_dependency':con.execute('SELECT COUNT(*) FROM dependency_registry WHERE read_only!=1').fetchone()[0],
    }
    result={'engine_version':con.execute("SELECT value FROM metadata WHERE key='engine_version'").fetchone()[0],'schema_version':con.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0],'config_id':con.execute("SELECT value FROM metadata WHERE key='config_id'").fetchone()[0],'dataset_id':con.execute("SELECT value FROM metadata WHERE key='dataset_id'").fetchone()[0],'candidates':con.execute('SELECT COUNT(*) FROM definition_candidates').fetchone()[0],'matches':con.execute('SELECT COUNT(*) FROM definition_matches').fetchone()[0],'evaluations':con.execute('SELECT COUNT(*) FROM block_evaluations').fetchone()[0],'zones':con.execute('SELECT COUNT(*) FROM institutional_zones').fetchone()[0],'transitions':con.execute('SELECT COUNT(*) FROM zone_state_transitions').fetchone()[0],'visits':con.execute('SELECT COUNT(*) FROM zone_visit_observations').fetchone()[0],'by_definition':by_definition,'causality_checks':checks,'sqlite_quick_check':con.execute('PRAGMA quick_check').fetchone()[0],'sqlite_integrity_check':con.execute('PRAGMA integrity_check').fetchone()[0],'foreign_key_errors':len(con.execute('PRAGMA foreign_key_check').fetchall())}
    con.close();return result

def main()->int:
    p=argparse.ArgumentParser();p.add_argument('--year',type=int,choices=(2023,2024),required=True);p.add_argument('--source',type=Path,required=True);p.add_argument('--group6',type=Path,required=True);p.add_argument('--group7-root',type=Path,required=True);p.add_argument('--outdir',type=Path,required=True);a=p.parse_args()
    root=a.group7_root.resolve();code=root/'code';files={'engine':code/'moebot_group7_engine.py','audit':code/'group7_independent_audit.py','visual':code/'group7_real_visual_audit.py','tests':code/'group7_test_suite.py','config':root/'FROZEN_CONFIG_REGISTRY.json'}
    source_identity={k:{'path':str(v),'sha256':sha256_file(v),'expected_sha256':EXPECTED_G7[k],'pass':sha256_file(v)==EXPECTED_G7[k]} for k,v in files.items()}
    if not all(v['pass'] for v in source_identity.values()): raise RuntimeError('Group7 frozen source identity mismatch')
    ensure_visual_runtime()
    sys.path.insert(0,str(code))
    from moebot_group7_engine import BASE_DEFINITIONS,DEFINITIONS,ENGINE_VERSION,SCHEMA_VERSION,build
    from group7_independent_audit import run as independent_audit
    from group7_real_visual_audit import run as visual_audit
    out=a.outdir.resolve();out.mkdir(parents=True,exist_ok=True);db=out/f'MoeBot_Group7_XAUUSD_{a.year}_v0.7.5_corrected_v3_group8_v1.sqlite';started=time.time()
    dep={'source':{'filename':a.source.name,'size_bytes':a.source.stat().st_size,'sha256':sha256_file(a.source)},'group6':{'filename':a.group6.name,'size_bytes':a.group6.stat().st_size,'sha256':sha256_file(a.group6)}}
    first=build(a.source,a.group6,db,recreate=True);second=build(a.source,a.group6,db,recreate=False);reimport={k:v for k,v in second['inserted'].items() if v!=0}
    audit=independent_audit(db,write_audit=True,source_override=a.source,group6_override=a.group6);visual_dir=out/f'visual_audit_{a.year}';visual=visual_audit(a.source,a.group6,db,visual_dir);summary=summarize(db,tuple(BASE_DEFINITIONS),tuple(DEFINITIONS))
    gates={'frozen_source_identity':all(v['pass'] for v in source_identity.values()),'engine_version':summary['engine_version']==ENGINE_VERSION,'schema_version':summary['schema_version']==SCHEMA_VERSION,'first_build_integrity':first['integrity']=='ok' and first['foreign_key_errors']==0,'idempotent_reimport':not reimport,'independent_audit':bool(audit['passed']),'summary_sqlite':summary['sqlite_quick_check']=='ok' and summary['sqlite_integrity_check']=='ok' and summary['foreign_key_errors']==0,'causality_zero_errors':all(v==0 for v in summary['causality_checks'].values()),'all_definitions_registered':set(summary['by_definition'])==set(DEFINITIONS),'all_definitions_nonempty':all(v['zones']>0 for v in summary['by_definition'].values()),'base_candidates_present':summary['candidates']>0,'causal_matches_present':summary['matches']>0,'real_visual_audit':bool(visual['passed'])}
    report={'format_version':1,'status':'PASS' if all(gates.values()) else 'FAIL','year':a.year,'lineage':'dukascopy_rebuild_v1_corrected_runtime_v3_group8_v1','source_group7_closure_tag':'moebot-group7-v0.7.5-closure','source_group7_closure_commit_sha':'c9a481d5d8f40bc80d833ef1d135fe56578b5fe2','engine_version':ENGINE_VERSION,'schema_version':SCHEMA_VERSION,'frozen_source_identity':source_identity,'verified_dependencies':dep,'database':{'filename':db.name,'path':str(db),'size_bytes':db.stat().st_size,'sha256':sha256_file(db)},'first_build':first,'reimport_nonzero':reimport,'independent_audit':audit,'summary':summary,'visual_audit':visual,'gates':gates,'passed':all(gates.values()),'elapsed_seconds':round(time.time()-started,3),'holdout_policy':'2024 uses the identical frozen v0.7.5 engine/config after 2023 dependency-lineage build; no result-driven changes','profitability_used':False}
    path=out/f'GROUP7_COHERENT_V3_YEAR_{a.year}.json';path.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n');print(json.dumps({'status':report['status'],'year':a.year,'database':report['database'],'summary':{k:summary[k] for k in ('candidates','matches','zones','transitions')},'audit':audit['summary'],'gates':gates},indent=2,sort_keys=True));return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
