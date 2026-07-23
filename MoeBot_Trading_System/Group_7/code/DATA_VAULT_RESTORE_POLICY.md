# Group 7 Data Vault Restore Policy

Annual Group 7 jobs consume only the published upstream Data Vault registry and verified public Release assets.

The shared restore utility must use bounded retries, extended transfer timeouts, optional GitHub-token authentication, per-part SHA-256 verification, compressed-stream SHA-256 verification, extracted database size/SHA-256 verification, and SQLite quick/integrity/foreign-key checks before Group 7 execution begins.

This policy changes no Group 7 definition, threshold, causal rule, frozen 2024 OOS rule, or closure gate.
