#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, re
from pathlib import Path

TARGETS = {
    "groups2_5/code/moebot_group2_engine_v0_2_1.py": (35853, "3d83dd19d36e790a71d4ee84db98c38eaf112ec4d9b0de88e54480f315173926"),
    "groups2_5/code/moebot_group3_structure_engine_v0_1_1.py": (23933, "8a44667aa6ca7b683c334223ccce011fdc9c5e1112a9c104a4a83d721531d512"),
    "groups2_5/code/moebot_group4_zones_engine_v0_1_6.py": (57168, "744aa2bdc48b74bdf462353819569bb9947085623b5bdf3f77dae76e7fb2a4ad"),
    "groups2_5/code/moebot_group5_liquidity_engine_v0_1_6.py": (59657, "97a062e465f5c488519b76cb84cd6596d9b665f16d3c95c59747d569b5a758bc"),
    "group6/code/moebot_group6_engine.py": (64524, "1a60e9943e91af656dfb9d698ae9b15aac185b173fceb60c5d72bb4b2114f877"),
}

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def fix_g4(path: Path) -> None:
    s = path.read_text(encoding="utf-8")
    block = """def cached_file_sha(path: str) -> str:\n    cache=path+'.sha256cache'\n    if os.path.exists(cache):\n        txt=open(cache,encoding='utf-8').read().strip().split()[0]\n        if len(txt)==64:return txt\n    h=hashlib.sha256()\n    with open(path,'rb') as f:\n        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)\n    return h.hexdigest()\n"""
    if block not in s:
        raise RuntimeError("G4 v2 cache helper signature not found")
    s = s.replace(block, "", 1)
    s = s.replace("SELECT timeframe,bar_id,atr FROM structure_states WHERE layer='internal' AND timeframe IN ('M15','H1','H4','D1')", "SELECT timeframe,bar_id,atr FROM structure_states WHERE layer='internal'", 1)
    s = s.replace("srcsha=cached_file_sha(source_db); g3sha=cached_file_sha(group3_db)", "srcsha=self._file_sha(source_db); g3sha=self._file_sha(group3_db)", 1)
    old = """def dataset_id_for(source_db:str,group3_db:str,cfg:Config)->str:\n    payload={\"source_sha256\":cached_file_sha(source_db),\"group3_sha256\":cached_file_sha(group3_db),\"config_id\":cfg.registry()[\"config_id\"],\"symbol\":\"XAUUSD_\"}\n    return stable_id(\"ds4\",payload)"""
    new = """def dataset_id_for(source_db:str,group3_db:str,cfg:Config)->str:\n    def fsha(p):\n        h=hashlib.sha256()\n        with open(p,\"rb\") as f:\n            for c in iter(lambda:f.read(1024*1024),b\"\"):h.update(c)\n        return h.hexdigest()\n    payload={\"source_sha256\":fsha(source_db),\"group3_sha256\":fsha(group3_db),\"config_id\":cfg.registry()[\"config_id\"],\"symbol\":\"XAUUSD_\"}\n    return stable_id(\"ds4\",payload)"""
    if old not in s:
        raise RuntimeError("G4 v2 dataset-id cache signature not found")
    s = s.replace(old, new, 1)
    s = s.replace("    bars_alive: int = 0\n\n\n\n\nclass Group4Engine:", "    bars_alive: int = 0\n\n\nclass Group4Engine:", 1)
    path.write_text(s, encoding="utf-8", newline="")

def fix_g5(path: Path) -> None:
    s = path.read_text(encoding="utf-8")
    old = """def sha256_file(path: str) -> str:\n    cache=path+'.sha256cache'\n    if os.path.exists(cache):\n        x=open(cache,encoding='utf-8').read().strip().split()[0]\n        if len(x)==64:return x\n    h=hashlib.sha256()\n    with open(path,'rb') as f:\n        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)\n    return h.hexdigest()"""
    new = """def sha256_file(path: str) -> str:\n    h = hashlib.sha256()\n    with open(path, \"rb\") as f:\n        for chunk in iter(lambda: f.read(1024 * 1024), b\"\"):\n            h.update(chunk)\n    return h.hexdigest()"""
    if old not in s:
        raise RuntimeError("G5 v2 cache signature not found")
    path.write_text(s.replace(old, new, 1), encoding="utf-8", newline="")

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--runtime-root",type=Path,required=True); a=ap.parse_args()
    root=a.runtime_root
    fix_g4(root/"groups2_5/code/moebot_group4_zones_engine_v0_1_6.py")
    fix_g5(root/"groups2_5/code/moebot_group5_liquidity_engine_v0_1_6.py")
    failed=[]
    for rel,(size,expected) in TARGETS.items():
        p=root/rel; actual_size=p.stat().st_size; actual=sha(p)
        ok=(actual_size==size and actual==expected)
        print(f"{'PASS' if ok else 'FAIL'} {rel} size={actual_size} sha256={actual}")
        if not ok: failed.append(rel)
    if failed: raise SystemExit("canonical source recovery failed: "+", ".join(failed))
    return 0
if __name__=="__main__": raise SystemExit(main())
