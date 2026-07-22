# Rebuild and Publication Contract

1. Never label a rebuilt database as byte-identical to a legacy database unless its full SHA-256 matches.
2. Never rename a rebuilt database to evade an exact dependency guard.
3. Use only XAU-USD BID M1 public data from the registered endpoint and preserve observed gaps.
4. Aggregate higher timeframes deterministically in UTC.
5. Run the exact frozen Group 2, 3, 4, 5, and 6 sources restored from the verified runtime bundle.
6. Require Group 2 verify, Group 5 synthetic tests, Group 6 selftest, Group 6 verify, `PRAGMA quick_check`, `PRAGMA integrity_check`, and `PRAGMA foreign_key_check` to pass.
7. Publish database, compressed-stream, and split-part SHA-256 identities.
8. Perform a clean-room restore using only public registry URLs before downstream use.
9. Revalidate Group 7 annually against the rebuilt dependency set. Group 8 remains unauthorized until the exact closure phrase is issued after all gates pass.
