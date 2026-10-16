# Retained native macOS validation

This directory contains the completed first-MVP validation of the source identified by `validation.json`. Run directly on the macOS ARM64 host; no Linux, container or VM measurements are mixed into it.

- 28 formal tests, no skips or missing successes. 17 tests launch the production relay and independent receiver processes; three test production Store behavior including real SQLite page exhaustion and supplemental deterministic commit failure; eight test report arithmetic/consistency using labeled synthetic fixtures.
- Four targeted behavior mutations detected by assertion failures, not by setup errors/timeouts.
- 18 fresh-database measured trials: three scenarios × two payload blob sizes × three repetitions, 60 events/trial at planned 15/s. All 1,080 accepted IDs and hashes match exactly one committed receiver effect. All trials appear in the summary.
- The receiver completion observation is sampled immediately after COMMIT returns. Its earlier transaction-record timestamp is retained separately and is not used for completion latency. Completion observations are in-memory telemetry; business effects and dedup receipts are durable.
- Relay CLI timing overrides: 0.3 s attempt timeout, 0.05 s retry base, 0.2 s cap. Actual normalized CLI arguments are retained in every trial. Defaults for persistent queue/receipt quotas are unchanged.
- Resource samples: relay RSS and apparent database/WAL/SHM lengths, nominal 10 ms interval; peaks can be missed. Only host-local relay process RSS is counted. Disk allocation blocks, write amplification and hardware power-failure behavior were not measured.

Re-run all steps into a NEW directory:

```sh
.venv/bin/python -m tools.validate --output results/local/validation --execution-label native-macos-host
```

Verify this retained report against current runtime/test/tool sources:

```sh
.venv/bin/python -m tools.check_report results/native-macos/benchmark
```

`validation.json` binds the source manifest, each step's exit/timeout/cleanup status and normalized output-log hash. `tests/tests.json` binds expected, started and successful IDs plus test-log hash. `mutations` retains failing assertions in isolated mutated copies. `benchmark/report.json` retains arrivals, acceptance statuses, post-commit sink observations, payload hashes, queue snapshots and RSS/disk samples. `report.html` is deterministically regenerated from JSON by the checker.

Earlier development/debug runs remain only under ignored `results/local/`; they are not published results. No live databases, payload spools, virtual environments or personal paths are included. This evidence is not a signed independent attestation, maximum-capacity benchmark or production reliability certification.
