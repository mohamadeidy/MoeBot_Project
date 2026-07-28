# MoeBot Groups 2–6 Dependency Archive

This directory is the canonical transfer location for frozen MoeBot runtime dependencies used by later groups.

## Current transfer status

The local execution workspace currently contains the exact frozen runtime sources for Groups 2–5 and several source/result databases, but it does **not** contain the exact Group 6 runtime source or the two official Group 6 annual SQLite databases.

No missing frozen file may be reconstructed, rewritten, or silently substituted and then described as the original.

## Exact frozen runtime sources verified locally

| Group | File | SHA-256 | Status |
|---|---|---|---|
| 2 | `moebot_group2_engine_v0_2_1.py` | `3d83dd19d36e790a71d4ee84db98c38eaf112ec4d9b0de88e54480f315173926` | exact local file available; Git transfer pending |
| 3 | `moebot_group3_structure_engine_v0_1_1.py` | `8a44667aa6ca7b683c334223ccce011fdc9c5e1112a9c104a4a83d721531d512` | exact local file available; Git transfer pending |
| 4 | `moebot_group4_zones_engine_v0_1_6.py` | `744aa2bdc48b74bdf462353819569bb9947085623b5bdf3f77dae76e7fb2a4ad` | exact local file available; Git transfer pending |
| 5 | `moebot_group5_liquidity_engine_v0_1_6.py` | `97a062e465f5c488519b76cb84cd6596d9b665f16d3c95c59747d569b5a758bc` | exact local file available; Git transfer pending |
| 6 | `moebot_group6_engine.py` | `1a60e9943e91af656dfb9d698ae9b15aac185b173fceb60c5d72bb4b2114f877` | exact runtime file not present in current workspace |

## Data files currently available locally

The following files exist in the current execution workspace and should be archived in compressed form or through Git LFS / release assets:

- `source_2023.sqlite`
- `source_2024_canonical.sqlite`
- `MoeBot_Group4_XAUUSD_2023_v0.1.6.sqlite`
- `MoeBot_Group4_XAUUSD_2024_v0.1.6.sqlite`
- `MoeBot_Group5_XAUUSD_2023_v0.1.6.sqlite`
- `MoeBot_Group5_XAUUSD_2024_v0.1.6.sqlite`

## Blocking missing annual dependencies

These exact official files are not present in the current workspace and therefore cannot yet be archived:

- `MoeBot_Group6_XAUUSD_2023_v0.6.4.sqlite`
- `MoeBot_Group6_XAUUSD_2024_v0.6.4.sqlite`

Their official identities remain recorded in the frozen manifests. Later groups must not use reconstructed or partial substitutes unless a formal rebuild is performed and recorded as a new artifact identity.

## Repository policy

- Store code, configs, reports, manifests, and compact dependency packs directly in Git.
- Store large SQLite databases through Git LFS, GitHub Releases, or deterministic split archives under 100 MiB per object.
- Every stored artifact must include its SHA-256 and extraction/reassembly instructions.
- A manifest or report is not a substitute for the runtime file or database it describes.
