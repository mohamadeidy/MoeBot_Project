# Exact Source Transfer Queue

These are the actual frozen runtime sources required by later MoeBot groups. A source is not considered archived in Git until its exact bytes are recoverable and its SHA-256 matches this registry.

| Group | Exact source file | Expected SHA-256 | Status |
|---|---|---|---|
| 1 | `MoeBot_Group1_MarketMemory_Collector_v0.9.2.mq5` | `5bad54ebdeadba2cdbb4cb63f8d411a4ccba68ae47f9dbe714627d48bf231bb7` | verified local identity; exact runtime copy still pending |
| 2 | `moebot_group2_engine_v0_2_1.py` | `3d83dd19d36e790a71d4ee84db98c38eaf112ec4d9b0de88e54480f315173926` | archived in verified Groups 2–6 runtime bundle |
| 3 | `moebot_group3_structure_engine_v0_1_1.py` | `8a44667aa6ca7b683c334223ccce011fdc9c5e1112a9c104a4a83d721531d512` | archived in verified Groups 2–6 runtime bundle |
| 4 | `moebot_group4_zones_engine_v0_1_6.py` | `744aa2bdc48b74bdf462353819569bb9947085623b5bdf3f77dae76e7fb2a4ad` | archived in verified Groups 2–6 runtime bundle |
| 5 | `moebot_group5_liquidity_engine_v0_1_6.py` | `97a062e465f5c488519b76cb84cd6596d9b665f16d3c95c59747d569b5a758bc` | archived in verified Groups 2–6 runtime bundle |
| 6 | `moebot_group6_engine.py` | `1a60e9943e91af656dfb9d698ae9b15aac185b173fceb60c5d72bb4b2114f877` | archived in verified Groups 2–6 runtime bundle |

## Runtime bundle

- Repository path: `MoeBot_Trading_System/archive/groups_2_6_frozen_runtime_bundle/`
- Restored archive: `MoeBot_Groups2-6_Frozen_Runtime_Sources.tar.zst`
- Archive SHA-256: `174f776cd8d0e8a56b253a98a18027a61351834cc490dd1bfb6b0eb8d63c56cf`
- Restore command: `python MoeBot_Trading_System/archive/groups_2_6_frozen_runtime_bundle/restore_bundle.py --extract-to ./restored_groups_2_6`

## Rules

- Do not reconstruct, rewrite, or silently patch a frozen source during transfer.
- Verify SHA-256 after restoration.
- A config, report, manifest, or version-lock file is not a substitute for the runtime source.
- Large SQLite/result artifacts follow `LARGE_DATA_ARTIFACTS.md`; their manifests are not substitutes for the files.
- Group 7 is not added until its formal closure and exact final delivery are available.
