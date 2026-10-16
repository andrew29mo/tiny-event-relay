# tiny-event-relay

A small, durable local HTTP event relay. Accept events into a bounded SQLite queue, retain them while the downstream is offline, and resume delivery after a process restart. The accompanying receiver demonstrates transactional deduplication, including the ambiguous case where the receiver commits but its acknowledgment is lost.

**Status:** private experimental MVP. No project license selected yet. This is working service code, with separate fault tests and measurement tools. It is not a distributed message broker or a production readiness claim.

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

## Reliability contract

- New submission: **202 after SQLite COMMIT**, using WAL and FULL synchronization; fullfsync/checkpoint_fullfsync are also requested. This acknowledges local persistence, not downstream delivery.
- Transfer is **at least once within the configured retry policy**. A receiver can commit and lose its response, causing a legitimate retransmission. Stable event IDs plus receiver-side transactional deduplication prevent duplicate effects in the demonstration. Arbitrary downstream services need their own idempotency support.
- Connection errors, timeouts, 408, 429 and 5xx retry with capped exponential jitter and capped Retry-After. Other statuses and exhausted retries are retained as dead letters, never silently dropped.
- Leases and claim tokens prevent stale completions from overriding newer claims. Exclusive data-directory ownership permits immediate in-flight recovery at startup.
- Unresolved count/payload limits and disk/free-space admission checks reject new work at capacity. Dead letters count toward quota. DB/WAL/SHM accounting is an **admission safeguard, not a hard filesystem quota**.
- Delivered payloads are cleared logically; compact receipts have bounded retention (default latest 10,000 and 24 hours). Deduplication is not promised beyond that window. SQLite files can retain high-water allocation and old bytes.

Defaults: 1,000 unresolved events, 8 MiB unresolved payload, 64 KiB/event, 64 MiB database-family disk admission budget, 16 MiB free-space reserve, 2 s attempt timeout, 0.25 s base / 30 s capped backoff, 24-hour retry horizon. All have command-line options; see `python -m relay serve --help` and the [full contract](docs/CONTRACT.md).

## Tests and retained measurements

```sh
.venv/bin/python -m unittest discover -v
# Full sequential run: formal tests, isolated mutations, benchmark, report checker.
# Output directory must not already exist; a failure/timeout is never a passing receipt.
.venv/bin/python -m tools.validate \
  --output results/local/validation \
  --execution-label native-macos-host
```

Use an accurate execution label on other hosts/VMs. The tools do not automatically establish whether the host is virtualized. The retained run below was performed directly on the native macOS host, not in Colima or a container.

The live process tests cover durable acceptance, actual disconnected listeners, SIGKILL/restart, a crash after receiver commit, lost acknowledgments, timeout recovery, duplicate/conflicting IDs, count/payload/disk admission limits, real SQLite page exhaustion, stale claim tokens, permanent failure/requeue and partial-request shutdown. Supplemental fault injection checks rollback on a commit error. Report tests use **synthetic fixtures for arithmetic and tamper detection only**, not for service correctness.

Four isolated source mutations must be detected as assertion failures: bypassing count quota, ignoring ID conflicts, accepting stale claim tokens, and removing receiver deduplication. A timeout/import/setup error does not count as successful mutation detection. These selected mutations are targeted evidence, not exhaustive proof.

Retained evidence:

- [Full validation receipt](results/native-macos/validation.json)
- [Formal tests](results/native-macos/tests/tests.txt) and [test-ID receipt](results/native-macos/tests/tests.json)
- [Mutation receipts](results/native-macos/mutations/mutations.json)
- [JSON with raw request/receiver/resource records](results/native-macos/benchmark/report.json)
- [HTML report](results/native-macos/benchmark/report.html)

Verify the current source and recompute metrics/HTML:

```sh
.venv/bin/python -m tools.check_report results/native-macos/benchmark
```

The source manifest binds all `relay`, `tools` and `tests` Python files, `pyproject.toml` and development requirements. README/CI metadata edits do not change this runtime/test manifest. It is a consistency hash, not a signed attestation.

Retained native macOS run: **28/28 tests**, **4/4 targeted mutations detected**, and **1,080/1,080 accepted events with matching unique committed effects** across 18 trials. No measured trial was omitted from the aggregate.

Each cell below is the median of three trial summaries; p95 values are medians of per-trial p95s, not pooled percentiles. Blob size excludes the JSON envelope.

| Scenario | Blob bytes | Accept p95 ms | Commit p95 ms | Unique effects/s | Relay peak RSS MiB | DB+WAL+SHM peak MiB | Drain s |
|---|---:|---:|---:|---:|---:|---:|---:|
| normal | 256 | 16.90 | 33.93 | 15.13 | 25.59 | 0.082 | — |
| normal | 16,384 | 16.02 | 33.24 | 15.12 | 25.86 | 0.133 | — |
| outage | 256 | 32.29 | 5276.95 | 9.96 | 25.64 | 0.098 | 1.86 |
| outage | 16,384 | 29.75 | 5578.59 | 9.84 | 27.03 | 1.071 | 1.92 |
| restart | 256 | 30.25 | 5433.31 | 9.81 | 25.55 | 0.102 | 1.83 |
| restart | 16,384 | 33.84 | 5510.21 | 9.61 | 27.06 | 1.071 | 1.95 |

Across all trials: maximum observed issue lag **15.79 ms**; maximum resource-sample gap **18.49 ms**. Offline/restart end-to-end latency includes the intentional outage and queue wait. These scenarios demonstrate recovery, not a speed advantage over the normal scenario.


## Measurement boundaries

Each fresh trial launches the formal relay CLI and a separate FULL-synchronous receiver. Two payload blob sizes (256 and 16,384 bytes), three scenarios (normal, offline backlog, offline + relay SIGKILL/restart), three repeats: 18 trials. Each submits 60 events at planned 15/s using the same IDs/payloads/offsets per workload. Actual issue lag is retained. Scenarios are shuffled with a fixed seed; trials run sequentially.

The receiver has a configured 3 ms response delay, including after recovery. This delay is separate from actual database I/O and event application. The receiver is absent during offline arrivals. Recovery begins only after all submissions are acknowledged, plus a 0.2 s hold; restart trials additionally kill/restart the relay before starting the receiver. Drain timing includes receiver startup. This is a controlled fault experiment, not a claim about a particular outage duration in deployment.

For bounded experiments, the formal relay CLI uses **0.3 s attempt timeout, 0.05 s retry base and 0.2 s retry cap**, rather than the service defaults. Other queue/receipt limits remain at defaults. These invocations come from `tests/support.py` and are bound by the source manifest; retries can affect drain timing. The measured data directory is temporary local storage on this host; filesystem type, hardware write traffic and storage-device durability are not separately established.

Acceptance latency measures invocation to HTTP acceptance response. End-to-end latency measures invocation to the receiver's committed unique business effect, which may precede the relay's receipt of the receiver acknowledgment. Cross-process timestamps use the local wall clock with a drift check; scheduled-arrival latency can be reconstructed from retained offsets. Throughput counts unique business effects over first invocation to last effect, including outage/recovery tails. It is **not maximum service capacity**; no nondurable baseline or speedup claim is made.

The receiver records commit-completion observation times in memory immediately after COMMIT returns. They are available for these fresh receiver trials; historical completion observations are unavailable after a receiver restart. The business-effect ledger and dedup receipts themselves are durable. The earlier transaction-record timestamp is retained separately and is not used as the end-to-end completion boundary.

RSS and DB/WAL/SHM file lengths are sampled nominally every 10 ms. RSS covers only the relay PID, across both lifetimes for restart trials; it excludes client/receiver/kernel/filesystem cache. File sizes are apparent lengths, not allocated blocks or bytes written. Short peaks can be missed; maximum observed sample gap is reported. Disk snapshots and raw samples are included, rather than estimating memory from payload size.

Only this native host was measured. The CI matrix targets Linux/macOS correctness, but remote status must be checked separately; configuration is not evidence that CI ran. No Linux/VM performance, Internet load, power-cut, disk-device failure, long-duration endurance or confidence intervals are claimed. Results depend heavily on SQLite synchronization and storage. See [security boundaries](SECURITY.md).

## Scope and licensing

Single local process, one worker, one configured destination. No strict delivery ordering, multi-node HA, authentication, secure deletion, automatic database compaction or universal exactly-once guarantee. Dead-letter listings return the oldest 100 entries; automatic discard/pagination is not included. OS hostname resolution can outlive network watchdog deadlines; use numeric IPs for strictly local operation.

The repository remains **Private**. A project license has not been selected; [third-party notices](THIRD_PARTY_NOTICES.md) distinguish runtime and development components. Public release requires a separate review and explicit authorization.
