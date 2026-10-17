# Historical 51-test run of ce620dc

This directory preserves the first cross-platform run. Its checker must be used from that revision; current 60-test evidence is in `../local-validation-reviewed/`.

# Retained local cross-platform validation

This is a completed native macOS / Colima Linux run, not a remote CI result. Start with [the separate environment tables](report.html) and [the combined receipt](combined.json). Recheck against the current source with:

```sh
.venv/bin/python -m tools.check_local reviews/local-validation
```

Both environments passed the same 51 tests and five targeted mutations, then completed 18 trials / 1,080 matching committed event effects each. Source bytes, complete test IDs, planned arrivals and payload hashes match. The Git base commit identifies the starting checkout; the snapshot manifest identifies the actual tested working bytes, including newly staged inputs.

Guest process RSS excludes host VM overhead. Different SQLite versions, CPU allocation and storage behavior prevent interpreting these tables as a cross-OS speedup or memory-saving comparison. The owned container was removed and the dedicated VM stopped; reusable images, VM disk and toolchain caches remain local.

`original-digests.json` records hashes before privacy normalization. Exported log paths/credentials were normalized and dependent hashes rebound before checking. This is a consistency record, not a signed independent attestation.

`checker-probes.json` records ten deliberately tampered copies rejected by the evidence checker. These are checker fault probes, not actual VM OOM or interruption experiments. Portable unit tests separately exercise real subprocess failure, timeout and detached-child cleanup; fake-Docker tests exercise export/recovery branches. The completed Colima run exercises actual successful export and cleanup.

See [the workflow and boundaries](../../docs/LOCAL_VALIDATION.md). Older review and MVP measurements are retained in explicitly historical directories.
