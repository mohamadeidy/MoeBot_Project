# MoeBot Groups 2–6 Frozen Runtime Bundle

This directory archives the **exact frozen runtime source code** and supporting
configuration/manifests for MoeBot Groups 2 through 6. It is designed as a
portable, auditable handoff for later Groups and new ChatGPT/Codex sessions.

## Why the archive is chunked

The verified `tar.zst` archive is stored as ordered Base64 chunks under
`chunks/`. This avoids silently rewriting source files and allows ordinary Git
to retain the exact bytes even when direct binary transfer between chat
sessions is unavailable.

Reconstruct and verify it with:

```bash
python MoeBot_Trading_System/archive/groups_2_6_frozen_runtime_bundle/restore_bundle.py \
  --extract-to ./restored_groups_2_6
```

The script refuses to proceed if the archive SHA-256 does not match.

## Bundle identity

- Archive: `MoeBot_Groups2-6_Frozen_Runtime_Sources.tar.zst`
- SHA-256: `174f776cd8d0e8a56b253a98a18027a61351834cc490dd1bfb6b0eb8d63c56cf`

## Frozen runtime source identities

| Group | Runtime source | SHA-256 |
|---|---|---|
| 2 | `moebot_group2_engine_v0_2_1.py` | `3d83dd19d36e790a71d4ee84db98c38eaf112ec4d9b0de88e54480f315173926` |
| 3 | `moebot_group3_structure_engine_v0_1_1.py` | `8a44667aa6ca7b683c334223ccce011fdc9c5e1112a9c104a4a83d721531d512` |
| 4 | `moebot_group4_zones_engine_v0_1_6.py` | `744aa2bdc48b74bdf462353819569bb9947085623b5bdf3f77dae76e7fb2a4ad` |
| 5 | `moebot_group5_liquidity_engine_v0_1_6.py` | `97a062e465f5c488519b76cb84cd6596d9b665f16d3c95c59747d569b5a758bc` |
| 6 | `moebot_group6_engine.py` | `1a60e9943e91af656dfb9d698ae9b15aac185b173fceb60c5d72bb4b2114f877` |

The archive also includes the Group 6 runners/tests, frozen configuration
registries, delivery manifests, and an internal source SHA-256 manifest.

## What this archive does not contain

It does **not** contain the multi-gigabyte annual SQLite result databases or
raw Collector archives. Ordinary Git is not an appropriate storage backend for
those artifacts. Their names, identities, required hashes, and storage policy
are documented in `../../registry/LARGE_DATA_ARTIFACTS.md`.

No downstream Group should substitute manifests or summaries for a required
SQLite dependency. The exact database must either be restored from an approved
artifact store or deterministically regenerated with the frozen code/config and
verified against its registered identity.
