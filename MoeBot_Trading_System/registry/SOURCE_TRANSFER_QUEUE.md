# Exact Source Transfer Queue

These are the actual frozen runtime sources required by later MoeBot groups. A source is not considered archived in Git until the exact file is committed and its SHA-256 matches this registry.

| Group | Exact source file | Expected SHA-256 | Status |
|---|---|---|---|
| 1 | `MoeBot_Group1_MarketMemory_Collector_v0.9.2.mq5` | `5bad54ebdeadba2cdbb4cb63f8d411a4ccba68ae47f9dbe714627d48bf231bb7` | verified local file; pending exact Git copy |
| 2 | `moebot_group2_engine_v0_2_1.py` | `3d83dd19d36e790a71d4ee84db98c38eaf112ec4d9b0de88e54480f315173926` | File Library source identified; pending exact Git copy |
| 3 | `moebot_group3_structure_engine_v0_1_1.py` | `8a44667aa6ca7b683c334223ccce011fdc9c5e1112a9c104a4a83d721531d512` | File Library source identified; pending exact Git copy |
| 4 | `moebot_group4_zones_engine_v0_1_6.py` | `744aa2bdc48b74bdf462353819569bb9947085623b5bdf3f77dae76e7fb2a4ad` | File Library source identified; pending exact Git copy |
| 5 | `moebot_group5_liquidity_engine_v0_1_6.py` | `97a062e465f5c488519b76cb84cd6596d9b665f16d3c95c59747d569b5a758bc` | File Library source identified; pending exact Git copy |
| 6 | `moebot_group6_engine.py` | `1a60e9943e91af656dfb9d698ae9b15aac185b173fceb60c5d72bb4b2114f877` | official manifest identity verified; pending exact Git copy |

## Rules

- Do not reconstruct, rewrite, or silently patch a frozen source during transfer.
- Verify SHA-256 after the Git copy.
- A config, report, manifest, or version-lock file is not a substitute for the runtime source.
- Group 7 is not added until its formal closure and exact final delivery are available.
