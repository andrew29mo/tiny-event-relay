# Historical MVP review of commit 1c29955

The findings below describe the prior 43-test review. Its native receipts are now historical under `results/historical-reviewed-1c29955`; use the old commit’s checker for those records. The current same-source macOS/Linux flow has 51 tests per environment and is documented in `docs/LOCAL_VALIDATION.md`.

# MVP review (2026-10-17)

Scope: production acceptance/delivery, restart ownership and claim tokens, bounded admission and dedup retention, tests exercising that implementation, measurement fairness and retained evidence. Repository remains Private, with no project license selected.

## Findings and changes

1. **Partial sampling could pass.** A resource sampler exception after collecting some observations previously left a usable-looking report. The exception is now propagated; sample start/end coverage, maximum 100 ms gaps and positive RSS coverage for each real PID/creation-time lifetime are enforced. Restart trials require both lifetimes. This does not turn sampling into an exact peak measurement.
2. **Validation interruption did not guarantee child cleanup.** The validator now reclaims owned children in `finally`, including detached/reparented children, and propagates owner chains through nested validators. Nonzero exit, timeout, interruption, successful parent with a leftover child, or incomplete cleanup cannot pass. These are cooperative same-user processes with inspectable environments; this is not a hostile-process containment boundary.
3. **Requeue storage failures closed the HTTP connection.** Actual SQLite-triggered failure through the production HTTP API now returns a structured 503. GET storage failures are handled consistently. Lost-client response writes are no longer confused with storage failures; a committed event can outlive a disconnected client.
4. **A zero-trial report could pass its checker.** Workload bounds, nonempty repeated coverage, source identity, sample coverage and completion timestamp bounds are now required. A new validation checker also verifies the full discovered test-ID set, command exit/timeout/cleanup status, log hashes, mutation assertions, raw measurements and deterministic HTML.
5. **Timing depended on wall-clock stability.** Receiver observation now captures `time.monotonic()` immediately after business COMMIT returns; the benchmark uses the same host clock. Wall time remains diagnostic. Both actual-invocation and scheduled-arrival p95s are retained to expose issuer lag. No comparative speedup or maximum throughput is claimed.
6. **Loopback binding did not reject browser origins or foreign Hosts.** A live probe returned 202 for both cases (`origin-boundary-before.json`). Relay and demo receiver now require matching loopback Host and reject browser Origin/cross-site Fetch Metadata; live tests verify rejection without queue entries or business effects and verify legitimate CLI traffic still delivers. This is not authentication against other local programs.
7. **Shared serializer could hide payload loss.** An isolated production serializer dropping the `b` field passed the original selected delivery test (`payload-oracle-before.json`, exit 0). The live test now independently decodes the receiver's stored payload and compares its contents with the original input. Benchmark and report expected bytes use the standard JSON contract directly, without calling production `canonical()`. A fifth targeted mutation verifies that field loss is now detected as an assertion failure.

## Evidence and limits

`before-fixes` preserves the new seven-test first pass against the original production/checker behavior: four successes, two assertion failures and one HTTP connection error. It includes newly added review tests, so its manifest is intentionally not the untouched `dd1e7a1` tree. No failed result is labeled as passed or mixed into current benchmark aggregates.

Added live-process tests challenge blocked SQLite writes before HTTP acceptance, actual SQL write rejection with no acknowledgment/effect, concurrent duplicate/count admission, requeue write failure and unresolved-event retention beyond receipt TTL. Existing real disconnected-listener, SIGKILL, after-sink-commit crash, lost-response, stale-token and page-exhaustion tests remain. Report fixtures test arithmetic and evidence validation only.

The reviewed implementation and all repeated performance trials are bound by `results/historical-reviewed-1c29955/validation.json`. The complete reviewed run must pass `python -m tools.check_validation results/native-macos`. Earlier first-MVP raw evidence is explicitly historical in `results/historical-mvp-dd1e7a1` and uses the old commit's checker.

Durability is supported by real database transactions and process-crash tests, not a hardware power-cut test. Queue count/payload caps are enforced, but DB/WAL/SHM admission accounting is a soft safeguard rather than a filesystem quota. At-least-once transfer requires receiver-side atomic deduplication within an appropriate retention window; the relay alone cannot promise exactly-once external effects. No Linux performance, Internet load, device failure, unlimited replay retention or production certification is implied.

Remote CI status and repository visibility are checked separately after upload. A configured workflow or a zero-step failure is not a successful remote test.

Seven tampered copies of real validated evidence were also rejected: missing test success, timeout disguised by exit zero, changed HTML, truncated samples, missing restart RSS lifetime, pre-invocation effect and a zero-trial report. `evidence-tamper-checks.json` binds the complete reviewed source, including the HTTP-origin guard. No forged metrics are retained as valid measurements.

Final native validation: 43 tests, five targeted mutations, 18 trials and 1,080 matching unique effects; zero step timeouts/interruption/cleanup reclaims. Source manifest SHA-256: `63863233000201bf7e4083112b8d362490eefc29e0bda110432a9e23adfb6416`. See the current README table and raw report for measured results, not historical first-MVP figures.
