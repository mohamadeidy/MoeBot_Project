#!/usr/bin/env python3
"""Merge exact annual categorical-intake reports into one cross-year dictionary."""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
from typing import Any

def canon(v:Any)->str:return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
def key(v:Any)->str:return canon(v)
def main()->int:
 p=argparse.ArgumentParser();p.add_argument('--reports-dir',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();reports={};fail=[]
 for year in (2023,2024):
  reports[str(year)]={}
  for group in ('source','group2','group3','group4','group5','group6','group7'):
   matches=list(a.reports_dir.rglob(f'CATEGORICAL_{group.upper()}_{year}.json'))
   if len(matches)!=1:fail.append(f'report_resolution:{group}:{year}:{len(matches)}');continue
   d=json.loads(matches[0].read_text());reports[str(year)][group]=d
   if d.get('status')!='PASS' or d.get('group')!=group or int(d.get('year',-1))!=year:fail.append(f'report_invalid:{group}:{year}')
 cross={}
 for group in ('source','group2','group3','group4','group5','group6','group7'):
  if any(group not in reports[y] for y in ('2023','2024')):continue
  cross[group]={};tables=set(reports['2023'][group]['categorical_values'])|set(reports['2024'][group]['categorical_values'])
  for table in sorted(tables):
   cross[group][table]={};fields=set(reports['2023'][group]['categorical_values'].get(table,{}))|set(reports['2024'][group]['categorical_values'].get(table,{}))
   for field in sorted(fields):
    v23=reports['2023'][group]['categorical_values'].get(table,{}).get(field,{}).get('values',[]);v24=reports['2024'][group]['categorical_values'].get(table,{}).get(field,{}).get('values',[])
    union_map={key(v):v for v in v23+v24};union=[union_map[k] for k in sorted(union_map)]
    cross[group][table][field]={'2023':v23,'2024':v24,'union':union,'present_both_years':sorted(set(map(key,v23))&set(map(key,v24))),'only_2023':[union_map[k] for k in sorted(set(map(key,v23))-set(map(key,v24)))],'only_2024':[union_map[k] for k in sorted(set(map(key,v24))-set(map(key,v23)))]}
 report={'format_version':1,'status':'PASS' if not fail else 'FAIL','groups':sorted(cross),'annual_report_hashes':{y:{g:d['report_hash'] for g,d in reports[y].items()} for y in ('2023','2024')},'cross_year':cross,'unknown_value_policy':'Unknown values are preserved raw and cannot be coerced into a frozen semantic binding.','failures':sorted(set(fail))};report['dictionary_hash']=hashlib.sha256(canon(report).encode()).hexdigest();a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n');print(json.dumps({'status':report['status'],'dictionary_hash':report['dictionary_hash'],'failure_count':len(report['failures'])},indent=2));return 0 if report['status']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
