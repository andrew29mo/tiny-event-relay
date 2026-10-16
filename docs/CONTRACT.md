# Delivery and capacity contract

## Acceptance and identity

`POST /v1/events` accepts exactly `event_id` and `payload`. ID: 1–128 ASCII letters, digits or `_.:-`. Payload: valid finite JSON, canonicalized by sorted object keys and compact ASCII JSON. Duplicate keys and non-finite constants are rejected. Default canonical payload limit: 65,536 bytes; wire envelope limit: six times that plus 1,024 bytes. Semantic number normalization is not provided (`1` and `1.0` can hash differently).

A new event receives **202 only after SQLite COMMIT**. WAL, synchronous=FULL, fullfsync=ON and checkpoint_fullfsync=ON are requested. Platforms that do not implement fullfsync retain their underlying SQLite synchronization behavior. Hardware/OS honesty is assumed; SIGKILL tests do not prove survival of power failure.

Same retained ID and canonical digest: 200 with existing state. Same retained ID and different digest: 409. After a response is lost or a 503 reports unknown acceptance, retry the **same ID and payload**. A 2xx acceptance response does not mean downstream delivery. A commit followed by checkpoint/response failure can leave a durable event even though the client did not see success.

## Transfer and recovery

One worker, fixed operator-configured HTTP(S) destination. No redirect following. Successful 2xx response headers mean acknowledgment; response bodies are not consumed. The receiver must only send success after its business transaction commits. Retry transport/timeout, 408, 429 and 5xx with exponential jitter, configured cap and capped Retry-After. Other statuses become dead letters. Delay/age bounds default to 0.25 s base, 30 s cap and 24-hour retry horizon. If the next failure retry would cross the horizon, preserve the event as dead-letter. A pending event recovered after a long shutdown may still make an attempt before its next failure is classified. No strict event-expiration or order guarantee.

Each claim has a lease and random token. Only the current in-flight token can finish it. Expired leases become pending. Exclusive process ownership permits immediate recovery of any in-flight state at startup. This is a local file-lock design, not distributed fencing. The worker holds no database transaction while doing network I/O.

Persisted due times, leases and retention use the host wall clock so they survive restarts. Large wall-clock changes can shift retry/retention timing; a reasonably maintained host clock is assumed. Monotonic benchmark timestamps remove wall-clock dependence from measured latency, not from these persistent scheduling policies.

Delivery is **at least once while within the retry policy**, with unresolved/permanent failures visibly retained. It is not guaranteed eventual success. A receiver can commit and lose its response: the relay must retry. Stable `Idempotency-Key` plus receiver-side deduplication handles this ambiguity. The demo receiver atomically inserts a unique receipt and an append-only business-effect row in the same FULL-synchronous SQLite transaction; the business-effect table deliberately does not have a unique event-ID constraint. Arbitrary remote side effects outside such a transaction need their own idempotency mechanism.

## Bounded storage

Defaults: 1,000 unresolved events, 8 MiB canonical unresolved payloads, 64 MiB database-family admission budget and 16 MiB host free-space reserve. Dead-letter and in-flight payloads count as unresolved. At capacity: 507, no eviction of accepted unresolved events. On SQLite/I/O error: 503 with unknown-acceptance guidance. Requeue only accepts dead letters and resets their retry cycle.

Admission checks current DB+WAL+SHM apparent sizes plus a conservative 256 KiB + four-times-payload reserve. Main DB max_page_count is also configured to approximately half the disk admission budget (with a minimum 128 pages). Checkpoint/truncate follows writes; updates need reserve too. These safeguards **do not enforce an exact filesystem-byte ceiling**, because SQLite pages/indexes/WAL, metadata and allocation vary. Small budgets can reject all submissions, including the test's 128 KiB budget. Use filesystem quotas if a hard external ceiling is required. Existing DB size can exceed a newly reduced budget; new admissions are then refused.

Delivered payload is set NULL, and compact ID/digest receipts remain for at most 24 hours and at most the latest 10,000 delivered receipts. Pruning occurs on submission and completion, not continuously during idle time. Within this dual window duplicates can be recognized; beyond it an old ID may be accepted as new. Receiver retention must cover the sender's actual retry/replay horizon. Database files retain their high-water allocation; deleting rows is not automatic compaction or secure erasure.

The dead-letter listing returns the oldest 100 entries. No discard, payload edit, pagination, multi-destination, multi-worker or automatic vacuum is included. Resolve the downstream problem and explicitly requeue; unresolved failures intentionally keep occupying quota.

## Resources and shutdown

HTTP clients must supply one matching loopback Host (with the bound port, except optional port 80). Origin-bearing and cross-site Fetch Metadata requests are rejected. These boundary errors use standard HTTP 400/403 error responses rather than API JSON. The relay and demo receiver share this CLI-only guard; trusted local programs remain unauthenticated. Management GET/requeue storage errors return structured 503 responses; a failed or lost requeue response requires inspecting the event state before retrying.

The intake API is deliberately serial, with a bounded listen backlog and two-second per-request watchdog. It may reject/reset excess connections rather than return a structured overload response. Disk-full admission is an explicit 507. SIGTERM/INT stops intake, interrupts a partial request and lets the active bounded transfer finish or fail; remaining persisted work is recovered next start. A hostname lookup can outlive the network watchdog (see SECURITY.md). No process-level hard RSS limit is promised.

Process counters are current-process observations, not durable cumulative totals. Queue state and attempts per unresolved event are durable. `delivered` counts only retained delivered receipts, not an all-time delivery total. `/health` reports worker storage errors; `/v1/stats` exposes state, disk and quota information. Inspect backlog age and dead-letter counts as well as liveness.
