# Group 7 v0.7.5 Runbook

## Synthetic preflight

```bash
pip install -r requirements.txt
python code/group7_test_suite.py --json-out SYNTHETIC_V075.json
python code/group7_independent_audit.py --db <synthetic-group7.sqlite>
```

## Annual build

Annual execution is owned by `.github/workflows/build-moebot-group7.yml`. It restores the published upstream 2023/2024 source and Group 6 databases, verifies exact SHA-256 and sizes, runs the frozen v0.7.5 engine, checks idempotence and causal integrity, generates real-data visual audits, publishes the Group 7 SQLite databases as Release assets, builds a permanent registry, and performs an independent clean-room restore before official closure.

## Future-group restore

```bash
python code/download_and_restore_group7.py \
  --registry registry/GROUP7_DATABASE_REGISTRY.json \
  --year both \
  --download-dir .group7_downloads \
  --output-dir group7_databases
```

Do not consume a registry whose status is not `published_verified_officially_closed`.
