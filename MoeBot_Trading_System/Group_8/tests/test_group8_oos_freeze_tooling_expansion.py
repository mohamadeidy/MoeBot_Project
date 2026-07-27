from __future__ import annotations
import tempfile,unittest
from pathlib import Path
import group8_freeze_oos_2024_sharded_v2 as v2


class ExpandedFreezeToolingTest(unittest.TestCase):
    def test_present_extra_tool_is_bound_and_base_list_restored(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);rel='code/group8_segmented_annual_core.py';p=root/rel;p.parent.mkdir(parents=True);p.write_text('fixture\n')
            old_freeze=v2.base.freeze;old=list(v2.base.OPTIONAL_FROZEN_TOOLING);seen=[]
            def fake_freeze(*,group8_root:Path,output:Path):
                seen.extend(v2.base.OPTIONAL_FROZEN_TOOLING)
                identities={r:{'path':r} for r in v2.base.OPTIONAL_FROZEN_TOOLING if (group8_root/r).is_file()}
                return {'status':'FROZEN_FOR_2024_OOS_FREE_SHARDED','manifest_hash':'x','identities':identities}
            try:
                v2.base.freeze=fake_freeze
                m=v2.freeze(group8_root=root,output=root/'oos.json')
            finally:
                v2.base.freeze=old_freeze
            self.assertIn(rel,seen);self.assertIn(rel,m['identities']);self.assertEqual(v2.base.OPTIONAL_FROZEN_TOOLING,old)

if __name__=='__main__':unittest.main()
