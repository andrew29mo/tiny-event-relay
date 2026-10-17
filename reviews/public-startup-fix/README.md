# Hosted macOS listener startup fix (2026-10-17)

The repository was already Public when its first fully executed hosted macOS CI exposed a startup defect. The main Ubuntu job and same-source local macOS/Colima runs passed; the hosted macOS job failed 23 integration tests while waiting for the demonstration receiver. No success was claimed for that run.

## Diagnosis from actual hosted execution

- [Initial hosted failure](https://github.com/andrew29mo/tiny-event-relay/actions/runs/39004645395): 60 tests, 23 failures, 221.160 seconds; the affected tests timed out waiting for receiver health.
- [Bounded startup diagnostic](https://github.com/andrew29mo/tiny-event-relay/actions/runs/39004974748): the actual receiver printed `constructing production Receiver` and entered `getfqdn('127.0.0.1')`, without returning before the 12-second subprocess timeout. This was not a SQLite assertion failure or a billing rejection.
- Inspection of Python's actual `HTTPServer.server_bind()` showed an unconditional `socket.getfqdn(host)` after TCP bind. The loopback service does not need a reverse-resolved server name. Upstream hostname resolution remains a separately documented limit.

## Minimal formal implementation change

The shared production `Server` now calls the underlying `TCPServer.server_bind()` and records its numeric bound address/port directly. Relay and demonstration receiver both use this class. Socket binding/reuse, browser/Host guards, queue transactions, FULL synchronization, FULL fsync settings, retries, resource checks, existing test timeouts and all original assertions remain unchanged.

The new regression test forbids `socket.getfqdn()` while constructing the real production Server, verifies the bound numeric address and actual ephemeral port, and closes the listener. `before-fix.txt` and `before-fix.json` record the expected assertion failure against the pre-fix Server with the newly added test; that source is intentionally not the untouched old test tree. After the fix it passes. Existing process-level tests still exercise actual relay/receiver persistence and HTTP delivery.

A bounded macOS CI smoke check also constructs the actual production receiver with reverse DNS forbidden, before the complete formal suite. It does not substitute a fake receiver or skip integration tests. The original tracing diagnostic is replaced by this shorter permanent regression guard.

## Current validation

Because source/tests changed, all retained current measurements were rerun using one immutable snapshot. Native macOS and Colima Linux each pass **61 tests, five targeted mutations, and 18 real trials / 1,080 matching event effects**. See `../local-validation-startup/combined.json` and the separately rendered native/VM tables. The old 60-test records were preserved as historical; no old receipt was rebound to the fixed source.

No throughput improvement is inferred from the startup fix. Initial startup is outside benchmark timing, restart startup is inside its scenario, and native/VM timing/RSS are separate environments. The owned container is removed and the owned VM stopped after validation. The latest hosted main CI result is checked separately after uploading this fix; the two failed diagnostic/pre-fix runs remain visible history.
