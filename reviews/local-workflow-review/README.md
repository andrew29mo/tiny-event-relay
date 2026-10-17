# Local validation and pre-publication review (2026-10-17)

Repository: tiny-event-relay. Keep Private; no project license decision or visibility change is part of this review.

## Finding and fix

Failed evidence export could leave a `*.partial-*` directory under tracked `reviews/` storage. A broad Git add could accidentally include an incomplete export. `retain_evidence()` now removes its temporary tree in `finally` after copy/normalization/check failure; the target is only renamed into place after all checks succeed. Git also ignores partial export directories. Two regression tests exercise export-check failure and a real UTF-8 copy/read failure, verify no target or partial tree survives, and preserve the raw source evidence.

The quick-start command also previously named an already committed retention directory, so it refused to run on an ordinary checkout. The default example now runs a fresh local validation; optional retention uses a fresh name. Existing evidence remains protected against overwrite.

## Verification scope

Seven additional formal controller tests exercise the real `run()` and its `finally` logic, with infrastructure commands mocked: native failure/timeout prevents VM start; attach timeout cannot pass even with container exit zero; nonzero/OOM/running/error container states fail; container removal/VM stop failure fails; an already-running dedicated VM is not stopped; zero-exit commands without complete receipts cannot pass. Mocked outcomes are not measured VM behavior or service correctness evidence. Existing portable tests exercise real nonzero subprocesses, timeout with SIGTERM exit zero, detached-child reclamation, snapshot edits/symlink escapes, and mocked export-before-removal ordering.

A real SIGTERM was sent during the first review run's native measurement. The outer command exited 130, both outer and nested receipts failed, no owned-environment process remained, and no VM was started. See `cancellation-probe.json`; this cancelled run is excluded from successful aggregates. There was no real container OOM experiment or physical power-cut test.

Ten tampered copies of the final evidence were rejected, including missing tests/driver, timeout disguised by exit zero, nonzero/OOM outcomes, surviving container/VM, network isolation changes, different planned arrivals and changed HTML. See `checker-probes.json`; rerun with `.venv/bin/python reviews/local-workflow-review/check_evidence_probes.py`. These probes are not runtime VM fault experiments.

The completed revision is bound by `../local-validation-reviewed/combined.json` and checked with:

```sh
.venv/bin/python -m tools.check_local reviews/local-validation-reviewed
.venv/bin/python -m tools.check_validation results/native-macos
```

The current source/tests and explicit setup files are copied into one immutable snapshot; both platforms run the complete production CLI test suite, targeted mutations, and identical planned workloads. New review tests bring the suite to 60 tests per environment. Old 51-test receipts remain historical, without rewriting their raw data. The native/guest tables are separate; no cross-OS speedup, maximum service capacity, total deployment RSS or physical disk-allocation claim is supported.

## Publication boundaries

- No project license is selected. Third-party notices remain separate; no external model/data or runtime Python dependency was added. License selection and public visibility require the owner's later decision.
- Local success is not remote CI success. Account billing/spending limits previously prevented both GitHub jobs from starting; inspect the latest run separately after upload.
- Actual repository checks before upload: Private, owner `andrew29mo`, only owner collaborator; Actions token defaults to read, cannot approve reviews; repository Actions secrets and variables each count zero. The workflow uses commit-pinned checkout/setup-python with checkout credential persistence disabled, no `pull_request_target`, and no write token permissions. Dependabot configuration exists.
- The repository's Actions policy currently allows all actions and does not require SHA pinning account-wide; the committed workflow itself pins its two actions. Ruleset inspection returned HTTP 403 because this Private account/repository plan does not support it. This is not proof of enabled branch protection. Secret-scanning status was not provided by the repository response. Recheck/enable supported protections after a separately authorized public transition; this review does not publish the repository to bypass plan restrictions.
- Before publication, preserve the documented local-only trust boundary, at-least-once semantics, bounded receipt retention, soft disk admission safeguard and process-crash-only durability evidence. Browser guards are not authentication. DNS resolution can outlive network timeouts.

The privacy pass covers tracked candidate text plus reachable historical blobs for common personal-path, GitHub/AWS credential and private-key patterns, and rejects unexpected environment/database/binary artifacts. Pattern scans cannot prove the absence of every possible secret. Personal Codex guidance, raw VM storage, toolchains and private environments remain local/ignored. Raw generated command logs may retain trailing whitespace intentionally so their hash-bound evidence is not silently reformatted.
