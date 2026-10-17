# Reviewed same-source macOS / Linux validation

Both environments passed the same **60 tests and five targeted mutations**, then completed 18 trials / 1,080 matching committed effects each. Source bytes, test IDs, planned arrival offsets and payload hashes match. No completed trial is omitted.

[Separate environment tables](report.html) · [Combined receipt](combined.json) · [Review findings](../local-workflow-review/README.md)

```sh
.venv/bin/python -m tools.check_local reviews/local-validation-reviewed
```

The base commit identifies the starting checkout; snapshot hashes identify the actual working bytes tested. Original pre-normalization digests are retained. Exported logs use path placeholders and rebound hashes; these are consistency receipts, not signed attestations.

Guest relay RSS excludes host VM overhead; DB/WAL/SHM values are apparent lengths. Different SQLite, CPU allocation and storage behavior prevent interpreting the separate tables as a cross-OS speedup or memory-saving comparison. Container removed; dedicated VM stopped; reusable local caches remain. Earlier 51-test receipts are historical under `../local-validation/`.
