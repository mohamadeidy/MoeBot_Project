#!/usr/bin/env python3
"""Build exact Group8 adapters from coherent corrected-v3 clean-room schemas."""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
from typing import Any
from group8_build_adapter_map import REQUIRED

def canon(v:Any)->str:return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
def clean_cols(report:dict[str,Any],group:str,table:str)->list[str]:
 try:return [str(x['name']) for x in report['groups'][group]['schema']['tables'][table]['columns']]
 except KeyError:return []
def source_cols(report:dict[str,Any],table:str)->list[str]:
 try:return [str(x['name']) for x in report['schema']['tables'][table]['columns']]
 except KeyError:return []
def main()->int:
 p=argparse.ArgumentParser();p.add_argument('--registry',type=Path,required=True);p.add_argument('--cleanroom-2023',type=Path,required=True);p.add_argument('--cleanroom-2024',type=Path,required=True);p.add_argument('--source-schema-2023',type=Path,required=True);p.add_argument('--source-schema-2024',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 reg=json.loads(a.registry.read_text());cr={'2023':json.loads(a.cleanroom_2023.read_text()),'2024':json.loads(a.cleanroom_2024.read_text())};src={'2023':json.loads(a.source_schema_2023.read_text()),'2024':json.loads(a.source_schema_2024.read_text())};fail=[];adapters={}
 if reg.get('status')!='PASS':fail.append('annual_registry_not_pass')
 for y in ('2023','2024'):
  if cr[y].get('status')!='PASS':fail.append(f'cleanroom_not_pass:{y}')
  if src[y].get('status')!='pass':fail.append(f'source_schema_not_pass:{y}')
  expected=reg['years'][y]['clean_room']['report_hash']
  if cr[y].get('report_hash')!=expected:fail.append(f'cleanroom_hash_mismatch:{y}')
 adapters={}
 for group,tables in REQUIRED.items():
  adapters[group]={}
  for table,required in tables.items():
   actual={}
   for y in ('2023','2024'):
    cols=source_cols(src[y],table) if group=='source' else clean_cols(cr[y],group,table)
    actual[y]=cols;missing=sorted(set(required)-set(cols))
    if missing:fail.append(f'{group}:{table}:{y}:missing:{",".join(missing)}')
   common=sorted(set(actual['2023'])&set(actual['2024']));stable=all(c in common for c in required)
   if not stable:fail.append(f'{group}:{table}:cross_year_unstable')
   row={'table':table,'required_columns':required,'actual_columns_2023':actual['2023'],'actual_columns_2024':actual['2024'],'required_columns_cross_year_stable':stable};row['adapter_hash']=hashlib.sha256(canon(row).encode()).hexdigest();adapters[group][table]=row
 report={'format_version':2,'status':'PASS' if not fail else 'FAIL','group':8,'lineage':reg.get('lineage'),'logical_lineage_id':reg.get('logical_lineage_id'),'annual_upstream_registry_hash':reg.get('registry_hash'),'adapter_policy':'Exact read-only table/column bindings verified against public clean-room coherent corrected-v3 annual SQLite schemas for source and Groups2-7; guessed identifiers forbidden.','adapters':adapters,'failures':sorted(set(fail))};report['adapter_map_hash']=hashlib.sha256(canon(report).encode()).hexdigest();a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n');print(json.dumps({'status':report['status'],'adapter_map_hash':report['adapter_map_hash'],'failure_count':len(report['failures'])},indent=2));return 0 if report['status']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
