#!/usr/bin/env python3
"""Formatting-tolerant wrapper for the proven locked-context semantics patch."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import group8_fix_locked_context_semantics as patch


def main() -> int:
    parser=argparse.ArgumentParser(add_help=False);parser.add_argument("--group8-root",type=Path,required=True)
    args,_=parser.parse_known_args()
    engine_path=args.group8_root.resolve()/"code/moebot_group8_engine_v0_8_0.py"
    text=engine_path.read_text()
    actual='        symbols=sorted({s for s,_ in self.bars_by_tf}); default_symbol=symbols[0] if len(symbols)==1 else "UNKNOWN"; valid_leg_ids={str(r["leg_id"]):dict(r) for r in self._validated_legs()}\n'
    normalized='        symbols=sorted({s for s,_ in self.bars_by_tf}); default_symbol=symbols[0] if len(symbols)==1 else "UNKNOWN"\n        valid_leg_ids={str(r["leg_id"]):dict(r) for r in self._validated_legs()}\n'
    if actual in text:
        if text.count(actual)!=1: raise SystemExit(f"process_ict actual head count={text.count(actual)}")
        engine_path.write_text(text.replace(actual,normalized,1))
    elif normalized not in text:
        raise SystemExit("process_ict formatting is neither authoritative nor normalized")
    sys.argv=[sys.argv[0],"--group8-root",str(args.group8_root)]
    return patch.main()


if __name__=="__main__": raise SystemExit(main())
