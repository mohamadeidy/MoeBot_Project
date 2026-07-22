# Group 1 Provenance

## Official runtime source

The official frozen collector is `MoeBot_Group1_MarketMemory_Collector_v0.9.2.mq5`, with SHA-256:

`5bad54ebdeadba2cdbb4cb63f8d411a4ccba68ae47f9dbe714627d48bf231bb7`

The source is archived under `../code/`.

## Design and verification history

The preserved Design Lock and detailed local verification report were produced for candidate `0.9.1`. Collector `0.9.2` is the officially locked runtime identity used for the accepted annual source packages and includes the final deinitialization catch-up repair.

The `0.9.1` verification report is retained as historical evidence for the shared collector core, database schema, idempotence, integrity, gap handling, and no-trading scope. It must not be misrepresented as a standalone full native verification of every `0.9.2` artifact.

## Files intentionally not committed

The native candidate ZIP, MT5 native test kit, Python wheel, raw Collector archives, and generated SQLite databases are not included as repository files here. Their official hashes remain recorded in `SHA256SUMS.txt` and `ANNUAL_SOURCE_DATABASES.json`.

Later groups require the exact collector source, frozen contracts, provenance registry, and verified annual database identity. They do not require the raw Collector archives during normal downstream execution.
