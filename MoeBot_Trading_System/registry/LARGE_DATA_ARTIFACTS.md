# MoeBot Large Data Artifact Registry

## Storage rule

Annual SQLite databases, Collector archives, and full delivery archives are
**immutable data artifacts**, not ordinary Git source files. They must be kept
in Git LFS, a GitHub Release asset store, or approved object storage. A manifest
or report is not a substitute for the actual database.

Before any downstream Group uses an artifact, verify:

1. exact filename;
2. byte size when registered;
3. SHA-256;
4. SQLite `quick_check`/`integrity_check` and foreign keys, when applicable;
5. upstream config and source fingerprints.

## Canonical source databases

| Artifact | Status in this Git branch | SHA-256 |
|---|---|---|
| `source_2023.sqlite` | Not stored in ordinary Git; available as a large external artifact | `b9295c8cecf7392105fb16e65fe66a1dd49cf309713c7f7a0e34f4c80bb6921c` |
| `source_2024_canonical.sqlite` | Not stored in ordinary Git; available as a large external artifact | `37ad342488338671c80e1f437a1fc2405d59b7824ea2d47e6d2823c8247daa36` |

## Group 6 frozen annual result databases

| Artifact | Registered size | Status in this Git branch | SHA-256 |
|---|---:|---|---|
| `MoeBot_Group6_XAUUSD_2023_v0.6.4.sqlite` | 2,196,496,384 bytes | Not currently available as an active local file; must be restored from approved full delivery or regenerated and verified | `0d7cbc8e4d749f597402136276524093c5b5b254b5948fc4c619be0188239c44` |
| `MoeBot_Group6_XAUUSD_2024_v0.6.4.sqlite` | 2,198,540,288 bytes | Not currently available as an active local file; must be restored from approved full delivery or regenerated and verified | `9023eafbe395622cedbc6158d91bff42d7ea018f9a7f0742524080761b5ce149` |

The approved full-delivery archive was registered as:

- `MoeBot_Group6_XAUUSD_2023-2024_v0.6.4_FULL_DELIVERY.tar.zst`
- SHA-256: `2bbb672e2b7aa80607597c2b830ebc3361c99796607093c4a92cdb48f0d83176`

## Other annual result databases

Group 2–5 annual databases and current/future Group outputs must follow the same
policy. Their code, configs, manifests, and handoff contracts belong in Git;
the data files belong in the approved artifact store, accompanied by registered
hashes and deterministic regeneration instructions.

## Prohibited substitutions

- Do not use old raw Collector ZIPs to reconstruct a frozen upstream Group when
  an approved result database is required.
- Do not use a report, CSV summary, screenshot, or manifest as if it contained
  the underlying rows.
- Do not silently regenerate a database with changed code, config, thresholds,
  source normalization, or dependency mapping.
