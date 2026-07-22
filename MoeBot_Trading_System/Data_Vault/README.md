# MoeBot Public SQLite Data Vault

This directory defines the permanent, reproducible storage and restoration path for the large annual SQLite dependencies used by later MoeBot groups.

## Critical lineage rule

The unavailable legacy Collector databases are **not** recreated under their old hashes. The public build is a new lineage named `dukascopy_rebuild_v1`, with new filenames and new SHA-256 identities. It uses the exact frozen Group 2–6 engines, but its market-data source is the public Dukascopy XAU/USD BID M1 feed rather than the unavailable broker Collector archives.

Therefore, Group 7 annual validation must be rerun and its dependency registry must explicitly accept the new published hashes. The old Group 7 checker must not be bypassed or tricked with renamed files.

## Outputs

For each year, the workflow publishes:

- one rebuilt source SQLite database;
- one rebuilt Group 6 SQLite database;
- split `.zst.part-NNN` release assets, each below the GitHub Release per-file limit;
- database, compressed-stream, and part-level SHA-256 hashes;
- source, pipeline, and SQLite verification reports.

## Permanent restore from a future chat or machine

After `registry/DATABASE_REGISTRY.json` reports `status: published`:

```bash
sudo apt-get install -y zstd
python MoeBot_Trading_System/Data_Vault/download_and_restore_databases.py --year both
```

The restore utility downloads the public Release assets, verifies every part, reconstructs the compressed streams, verifies the SQLite hashes, decompresses them, and runs SQLite integrity and foreign-key checks.

## Publication trigger

The repository must be public. The workflow is deliberately blocked while the repository is private to avoid consuming private GitHub Actions minutes. It starts automatically on GitHub's `public` event when repository visibility changes to public, and it can also be rerun manually afterward.

## Cost control

The design uses public GitHub Actions and public GitHub Release assets, not Git LFS. Large databases are never committed into Git history.
