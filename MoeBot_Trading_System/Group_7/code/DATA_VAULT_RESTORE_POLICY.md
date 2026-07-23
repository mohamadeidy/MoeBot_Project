# Group 7 Data Vault Restore Policy

Annual Group 7 jobs consume only the published upstream Data Vault registry and verified public Release assets.

The shared restore utility must use bounded retries, extended transfer timeouts, resumable transfers for large Release assets, optional GitHub-token authentication only for API endpoints, per-part SHA-256 verification, compressed-stream SHA-256 verification, extracted database size/SHA-256 verification, and SQLite quick/integrity/foreign-key checks before Group 7 execution begins.

Published databases compressed with `zstd --long=31` must be decompressed with the same long-window allowance. The decoder must reject any stream whose verified identity, extracted size, or SQLite integrity differs from the registry.

A partial transfer may be resumed, but no partial or unverified byte stream may enter Group 7. A completed part is accepted only after its registered SHA-256 matches exactly.

This policy changes no Group 7 definition, threshold, causal rule, frozen 2024 OOS rule, or closure gate.
