# tiny-event-relay

A small, durable local HTTP event relay. Accept events into a bounded SQLite queue, retain them while the downstream is offline, and resume delivery after a process restart. The accompanying receiver demonstrates transactional deduplication, including the ambiguous case where the receiver commits but its acknowledgment is lost.

**Status:** public experimental MVP. Licensed under [MIT](LICENSE). This is working service code, with separate fault tests and measurement tools. It is not a distributed message broker or a production readiness claim.

```text
producer -> loopback HTTP intake -> SQLite WAL -> one delivery worker -> configured HTTP(S) sink
                                      ^                 |
                                      +-- retry / ack --+
```

## Run the service

Python 3.12+, macOS or Linux. The relay and demonstration receiver use only the Python standard library. `psutil` is needed only for measurement/validation tools.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
mkdir -p results/local/demo
```

Terminal 1: start the example receiver (loopback, unauthenticated demo only).

```sh
.venv/bin/python -m tools.receiver --db results/local/demo/sink.sqlite --port 8081
```

Terminal 2: start the actual relay.

```sh
.venv/bin/python -m relay serve \
  --data-dir results/local/demo/queue \
  --upstream http://127.0.0.1:8081/events \
  --port 8080
```

Terminal 3:

```sh
.venv/bin/python -m relay submit event-001 '{"temperature":23.5}'
.venv/bin/python -m relay get event-001
.venv/bin/python -m relay stats
.venv/bin/python -m relay dead-letters
```

Stop the receiver, submit more events, and restart it using the same database. Pending events are retried. Stop/restart the relay using the same data directory to resume its durable queue. Sending the same ID and payload again returns its retained state; changing the payload under a retained ID returns a conflict. To retry a dead letter after fixing the downstream:

```sh
.venv/bin/python -m relay requeue event-001
```

Both services bind to `127.0.0.1`. Do not expose the demo receiver or relay directly to an untrusted network. Its fault-control endpoint is intentionally unsafe for production exposure.

This is a CLI/local-program API: matching loopback Host is required; browser Origin and cross-site Fetch Metadata requests are rejected. These checks are not authentication against other local programs. Browser frontends and arbitrary reverse-proxy Host values are outside the MVP.

## Reliability contract

- New submission: **202 after SQLite COMMIT**, using WAL and FULL synchronization; fullfsync/checkpoint_fullfsync are also requested. This acknowledges local persistence, not downstream delivery.
- Transfer is **at least once within the configured retry policy**. A receiver can commit and lose its response, causing a legitimate retransmission. Stable event IDs plus receiver-side transactional deduplication prevent duplicate effects in the demonstration. Arbitrary downstream services need their own idempotency support.
- Connection errors, timeouts, 408, 429 and 5xx retry with capped exponential jitter and capped Retry-After. Other statuses and exhausted retries are retained as dead letters, never silently dropped.
- Leases and claim tokens prevent stale completions from overriding newer claims. Exclusive data-directory ownership permits immediate in-flight recovery at startup.
- Unresolved count/payload limits and disk/free-space admission checks reject new work at capacity. Dead letters count toward quota. DB/WAL/SHM accounting is an **admission safeguard, not a hard filesystem quota**.
- Delivered payloads are cleared logically; compact receipts have bounded retention (default latest 10,000 and 24 hours). Deduplication is not promised beyond that window. SQLite files can retain high-water allocation and old bytes.

Defaults: 1,000 unresolved events, 8 MiB unresolved payload, 64 KiB/event, 64 MiB database-family disk admission budget, 16 MiB free-space reserve, 2 s attempt timeout, 0.25 s base / 30 s capped backoff, 24-hour retry horizon. All have command-line options; see `python -m relay serve --help` and the [full contract](docs/CONTRACT.md).

## Tests and retained measurements

The default local cross-platform workflow is:

```sh
./tools/validate-local
.venv/bin/python -m tools.check_local reviews/local-validation-startup
```

The first command creates a fresh local run; the second rechecks the committed reviewed evidence. To retain a new run for Git, pass a fresh `--retain` directory as described in [the workflow guide](docs/LOCAL_VALIDATION.md).

It uses an existing project Python 3.12 environment or creates `.venv` with `python3.12` (override `TINY_EVENT_PYTHON` if needed), installs the pinned measurement dependency, and installs checksum-pinned Colima/Lima into ignored local storage. An installed Docker CLI/buildx is required; Docker Desktop does not need to run. Apple Virtualization support is required. The retained run here uses ARM64; Intel assets are available but were not exercised on this host.

One immutable snapshot supplies native macOS and Linux. New source files must be tracked/staged before they become validation inputs. The snapshot includes all formal runtime/test/tool Python files and explicit validation setup files; it excludes spools, credentials, environments and historical reports. Native runs in a fresh environment with the dedicated VM stopped. Linux runs in a non-root container with no external network or host mounts, an init process, four-CPU quota and 4 GiB memory, inside a dedicated 4-vCPU/6-GiB Colima VM. Architecture, source hashes, complete successful test-ID lists and planned payload/arrival schedules must agree.

The VM profile and Docker configuration belong to this project. An already-running owned VM is refused; unrelated profiles are not stopped. Failed commands, timeout, interruption, OOM, missing source/test coverage or failed cleanup cannot pass. Evidence is exported before the owned container is removed; failed recovery export retains the stopped container for inspection. The owned VM is stopped at exit. VM disks/images and verified toolchain caches are deliberately retained for reuse, rather than claiming zero residual disk allocation.

Raw evidence is written under ignored `results/local/dual-*`. `--retain` creates a fresh privacy-normalized directory under `reviews/`, records original digests and rechecks normalized evidence. It never overwrites an existing directory: choose a new `--retain` name for another retained run. The command does not commit, publish or change GitHub visibility. [Dual-platform overview](reviews/local-validation-startup/report.html) · [combined receipt](reviews/local-validation-startup/combined.json).

Single-environment commands remain available:

```sh
.venv/bin/python -m unittest discover -v
# Full sequential run: formal tests, isolated mutations, benchmark, report checker.
# Output directory must not already exist; a failure/timeout is never a passing receipt.
.venv/bin/python -m tools.validate \
  --output results/local/validation \
  --execution-label native-macos-host
```

For manual single-environment runs, use an accurate execution label; that runner does not detect virtualization automatically. The dual-platform controller sets and verifies its labels. The native table below comes from macOS host processes, and the Linux table comes from the dedicated Colima VM/container.

The live process tests cover durable acceptance, actual disconnected listeners, SIGKILL/restart, a crash after receiver commit, lost acknowledgments, timeout recovery, duplicate/conflicting IDs, count/payload/disk admission limits, real SQLite page exhaustion, stale claim tokens, permanent failure/requeue and partial-request shutdown. Supplemental fault injection checks rollback on a commit error. Expected benchmark bytes come directly from the standard JSON contract, without invoking production serialization; the live delivery test also independently decodes the receiver’s stored payload. Report tests use **synthetic fixtures for arithmetic and tamper detection only**, not for service correctness.

Five isolated source mutations must be detected as assertion failures: payload field loss, bypassing count quota, ignoring ID conflicts, accepting stale claim tokens, and removing receiver deduplication. A timeout/import/setup error does not count as successful mutation detection. These selected mutations are targeted evidence, not exhaustive proof.

Retained evidence:

- [Full validation receipt](results/native-macos/validation.json)
- [Formal tests](results/native-macos/tests/tests.txt) and [test-ID receipt](results/native-macos/tests/tests.json)
- [Mutation receipts](results/native-macos/mutations/mutations.json)
- [JSON with raw request/receiver/resource records](results/native-macos/benchmark/report.json)
- [HTML report](results/native-macos/benchmark/report.html)

Verify the current source and recompute metrics/HTML:

```sh
.venv/bin/python -m tools.check_report results/native-macos/benchmark
.venv/bin/python -m tools.check_validation results/native-macos
```

The source manifest binds all `relay`, `tools` and `tests` Python files, `pyproject.toml` and development requirements. README/CI metadata edits do not change this runtime/test manifest. It is a consistency hash, not a signed attestation.

Retained same-source run: **61/61 tests and 5/5 targeted mutations in each environment**. All **2,160 accepted events** across **36 trials** match exactly one committed effect per trial event. No measured trial from the run was omitted.

Each cell is the median of three trial summaries; p95 values are medians of trial p95s, not pooled percentiles. RSS/disk values are sampled peaks in the measurement window. Blob size excludes the JSON envelope.

### Native macOS host processes

| Scenario | Blob bytes | Accept p95 ms | Commit p95 ms | Unique effects/s | Relay RSS MiB | DB+WAL+SHM MiB | Drain s |
|---|---:|---:|---:|---:|---:|---:|---:|
| normal | 256 | 13.35 | 27.46 | 15.11 | 25.45 | 0.086 | — |
| normal | 16,384 | 14.55 | 29.59 | 15.13 | 25.72 | 0.133 | — |
| outage | 256 | 24.03 | 5100.50 | 10.12 | 25.52 | 0.098 | 1.75 |
| outage | 16,384 | 24.22 | 4857.90 | 10.18 | 27.16 | 1.071 | 1.72 |
| restart | 256 | 24.46 | 5116.07 | 10.00 | 25.52 | 0.098 | 1.71 |
| restart | 16,384 | 26.45 | 5307.54 | 10.04 | 26.92 | 1.071 | 1.70 |

### Linux inside Colima + container

| Scenario | Blob bytes | Accept p95 ms | Commit p95 ms | Unique effects/s | Relay RSS MiB | DB+WAL+SHM MiB | Drain s |
|---|---:|---:|---:|---:|---:|---:|---:|
| normal | 256 | 4.50 | 7.10 | 15.22 | 23.17 | 0.074 | — |
| normal | 16,384 | 4.37 | 7.42 | 15.21 | 23.25 | 0.137 | — |
| outage | 256 | 4.07 | 4095.99 | 13.27 | 23.21 | 0.090 | 0.37 |
| outage | 16,384 | 4.89 | 4243.32 | 13.28 | 24.31 | 1.086 | 0.38 |
| restart | 256 | 3.55 | 4216.76 | 13.10 | 23.19 | 0.090 | 0.40 |
| restart | 16,384 | 3.74 | 4228.16 | 13.17 | 24.28 | 1.086 | 0.37 |

These are separate environment measurements, not a cross-OS optimization result. Both use Python 3.12.14 and psutil 7.0.0. Native SQLite is 3.53.1 with 15 visible host CPUs; the guest uses SQLite 3.40.1 and four vCPUs. Filesystem, synchronization and memory accounting also differ. The container has a 4 GiB limit; the VM has 6 GiB configured RAM. Guest relay RSS excludes host VM overhead, and apparent DB sizes are not VM image allocation.

native: maximum issue lag **10.31 ms**, maximum sample gap **17.57 ms**.

linux: maximum issue lag **10.24 ms**, maximum sample gap **19.11 ms**.

The [workflow review](reviews/local-workflow-review/README.md) records the export cleanup fix, controller fault coverage, real cancellation probe and publication boundaries.

## Measurement boundaries

Each fresh trial launches the formal relay CLI and a separate FULL-synchronous receiver. Two payload blob sizes (256 and 16,384 bytes), three scenarios (normal, offline backlog, offline + relay SIGKILL/restart), three repeats: 18 trials. Each submits 60 events at planned 15/s using the same IDs/payloads/offsets per workload. Actual issue lag is retained. Scenarios are shuffled with a fixed seed; trials run sequentially.

The receiver has a configured 3 ms response delay, including after recovery. This delay is separate from actual database I/O and event application. The receiver is absent during offline arrivals. Recovery begins only after all submissions are acknowledged, plus a 0.2 s hold; restart trials additionally kill/restart the relay before starting the receiver. Drain timing includes receiver startup. This is a controlled fault experiment, not a claim about a particular outage duration in deployment.

For bounded experiments, the formal relay CLI uses **0.3 s attempt timeout, 0.05 s retry base and 0.2 s retry cap**, rather than the service defaults. Other queue/receipt limits remain at defaults. These invocations come from `tests/support.py` and are bound by the source manifest; retries can affect drain timing. The measured data directory is temporary local storage on this host; filesystem type, hardware write traffic and storage-device durability are not separately established.

Acceptance latency measures invocation to HTTP acceptance response. End-to-end latency measures invocation to the receiver's committed unique business effect, which may precede the relay's receipt of the receiver acknowledgment. Cross-process completion times use the same host-wide monotonic clock (Python 3.12 on the supported macOS/Linux platforms); wall timestamps are diagnostic only. Invocation-based and scheduled-arrival p95s are both retained in JSON. Throughput counts unique business effects over first invocation to last effect, including outage/recovery tails. It is **not maximum service capacity**; no nondurable baseline or speedup claim is made.

The receiver records commit-completion observation times in memory immediately after COMMIT returns. They are available for these fresh receiver trials; historical completion observations are unavailable after a receiver restart. The business-effect ledger and dedup receipts themselves are durable. The earlier transaction-record timestamp is retained separately and is not used as the end-to-end completion boundary.

RSS and DB/WAL/SHM file lengths are sampled nominally every 10 ms. Sampling exceptions, gaps over 100 ms, incomplete window coverage or missing positive RSS samples for any relay lifetime fail validation. PID and process-creation time bind each RSS observation to the intended child. RSS covers only the relay PID, across both lifetimes for restart trials; it excludes client/receiver/kernel/filesystem cache. File sizes are apparent lengths, not allocated blocks or bytes written. Short peaks can still be missed; maximum observed sample gap is reported. The after-drain database-family size is retained separately. Disk snapshots and raw samples are included, rather than estimating memory from payload size.

The first process starts before the measurement window, so its initial startup peak is not measured. Restart startup falls inside that scenario's window. These are sampled peaks during the declared experiment, not lifetime maximum RSS or total deployment memory.

Native macOS and Linux-in-Colima measurements are reported separately. Linux relay RSS is guest-process RSS, excluding the host VM, kernel, receiver, client and images. The container's filesystem and synchronization behavior differ from the host; its apparent DB sizes are not host VM-disk allocation. These measurements do not establish native Linux speedup or cross-OS memory savings. No Internet load, power-cut, disk-device failure, long-duration endurance or confidence intervals are claimed. Results depend heavily on SQLite synchronization and storage. The CI matrix targets Linux/macOS correctness, but remote status must be checked separately; configured workflows and local Linux success are not a remote CI pass. See [security boundaries](SECURITY.md).

## Scope and licensing

Single local process, one worker, one configured destination. No strict delivery ordering, multi-node HA, authentication, secure deletion, automatic database compaction or universal exactly-once guarantee. Dead-letter listings return the oldest 100 entries; automatic discard/pagination is not included. OS hostname resolution can outlive network watchdog deadlines; use numeric IPs for strictly local operation.

Original project code and documentation are licensed under the [MIT License](LICENSE), copyright (c) 2026 Andrew Yuan. [Third-party components](THIRD_PARTY_NOTICES.md) retain their own licenses.

Public status, repository protections and anonymous-read verification are recorded in the [release check](reviews/public-release/README.md).
