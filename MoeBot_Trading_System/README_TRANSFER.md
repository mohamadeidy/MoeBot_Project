# MoeBot Trading System — Portable Transfer Contract

This directory is the canonical Git handoff location for MoeBot frozen runtime
source code, design/config locks, manifests, and downstream dependency rules.

## Available in Git

- Frozen runtime source bundle for Groups 2–6:
  `archive/groups_2_6_frozen_runtime_bundle/`
- Exact source identities and transfer status:
  `registry/SOURCE_TRANSFER_QUEUE.md`
- Large immutable data artifact registry:
  `registry/LARGE_DATA_ARTIFACTS.md`
- Group-specific version/config/design locks already present under each Group
  directory.

Restore Groups 2–6 exact runtime sources with:

```bash
python MoeBot_Trading_System/archive/groups_2_6_frozen_runtime_bundle/restore_bundle.py \
  --extract-to ./restored_groups_2_6
```

The restored archive is accepted only when its SHA-256 equals:

`174f776cd8d0e8a56b253a98a18027a61351834cc490dd1bfb6b0eb8d63c56cf`

## Not stored in ordinary Git

Multi-gigabyte SQLite annual databases, raw Collector archives, and full binary
deliveries are not committed to ordinary Git. `.gitattributes` prepares these
extensions for Git LFS, but LFS or a release/object-storage backend must be
configured before uploading them.

A later Group must not treat reports or manifests as substitutes for required
SQLite rows. Restore an approved artifact or deterministically regenerate it
with the frozen code/config, then verify the registered SHA-256 and database
integrity.

## Future Groups

At each official Group closure, produce and archive:

1. exact frozen runtime source;
2. design/config/version locks;
3. verification and final verdict reports;
4. SHA-256 manifests;
5. a compact next-Group dependency pack where feasible;
6. a large-artifact registry entry for any SQLite/full-delivery artifact that
   must remain outside ordinary Git.

Do not archive a Group candidate as final before its explicit official closure.
