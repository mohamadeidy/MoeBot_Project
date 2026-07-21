# Group 6 → Group 7 Exact Handoff Requirements

Group 7 must consume these exact frozen annual SQLite artifacts. Raw Collector archives or rebuilt substitutes are not accepted.

| Year | Role | Exact filename | Size | SHA-256 |
|---|---|---|---:|---|
| 2023 | canonical source bars | `source_2023.sqlite` | verify by hash | `b9295c8cecf7392105fb16e65fe66a1dd49cf309713c7f7a0e34f4c80bb6921c` |
| 2023 | Group 6 direct dependency | `MoeBot_Group6_XAUUSD_2023_v0.6.4.sqlite` | 2,196,496,384 | `0d7cbc8e4d749f597402136276524093c5b5b254b5948fc4c619be0188239c44` |
| 2024 | corrected canonical source bars | `source_2024_canonical.sqlite` | verify by hash | `37ad342488338671c80e1f437a1fc2405d59b7824ea2d47e6d2823c8247daa36` |
| 2024 | Group 6 direct dependency | `MoeBot_Group6_XAUUSD_2024_v0.6.4.sqlite` | 2,198,540,288 | `9023eafbe395622cedbc6158d91bff42d7ea018f9a7f0742524080761b5ce149` |

The input validator must reject partial databases, content-changing renames, rebuilt variants, and any file whose SHA-256 does not match.
