# Same-source macOS / Linux validation

```sh
./tools/validate-local
.venv/bin/python -m tools.check_local reviews/local-validation-mit
```

The first command runs a new validation into ignored local storage; the second checks the already committed reviewed evidence. To export a new successful run, use a fresh retention directory, for example:

```sh
./tools/validate-local --retain "reviews/local-validation-$(date -u +%Y%m%dT%H%M%SZ)"
```

An existing retained directory is never overwritten. The raw directory defaults to an ignored timestamped `results/local/dual-*`; `--output` may name a fresh directory under `results/local/`. The wrapper bootstraps the project environment with Python 3.12 when needed and installs the pinned measurement dependency. Set `TINY_EVENT_PYTHON` to an installed Python 3.12 interpreter if it is not on PATH. Docker CLI/buildx must be installed; the existing Docker Desktop application binaries can be reused without running Docker Desktop. Pinned official Colima/Lima binaries are installed under ignored local storage and verified before use.

## What actually runs

1. Acquire an exclusive project validation lock. Refuse an already-running dedicated `relay` VM; do not take over someone else's running profile.
2. Inventory the tracked runtime, tools, tests, requirements, explicit setup files and project license/notice files. New source files must be staged/tracked. Copy these bytes to an isolated workspace, bind their hashes, and verify before/after execution. The Git base commit is recorded separately: the input manifest, rather than an assertion about an unchanged HEAD tree, identifies the actual bytes tested.
3. Create a fresh native Python environment. Run the complete production CLI tests, five targeted mutations, 18 real measurement trials and report checks while the owned VM is stopped.
4. Start a project-specific Colima home/profile with 4 vCPU and 6 GiB RAM, native architecture, no Rosetta/binfmt emulation or host mounts. Do not activate a global Docker context. Use a project-local Docker configuration/socket.
5. Build the pinned official Python 3.12.14 container from the same source snapshot. Run the identical driver as a non-root user, with an init process, no external network or host mounts, 4 CPU quota and 4 GiB memory. SQLite temporary databases use the container filesystem, not a host bind or tmpfs substitute.
6. Inspect the actual container exit/OOM state, export its evidence, remove the owned container and stop the owned VM. Bind the raw image/container inspections and final VM list to the combined receipt. Failed recovery export retains a stopped container rather than deleting the only remaining evidence.
7. Verify identical complete successful test IDs, source manifests, import locations, planned arrivals and payload hashes. Verify logs, image snapshot binding, actual exit, isolation and cleanup. Render separate native and VM tables; export privacy-normalized evidence into a fresh directory and check it again.

The outer lifecycle executor bounds subprocesses and reclaims cooperative same-user tagged descendants, including new-session/reparented children. Native test processes inherit ownership chains through nested validators. Colima/Docker infrastructure is managed separately so that starting a daemon is not mistaken for a leaked test process. Interruption, timeout, nonzero exit, OOM, orphan reclamation or failed cleanup cannot produce a successful outcome.

## Retained evidence

- `combined.json`: snapshot manifest, base commit, operation outcomes and cleanup.
- `native/`, `linux/`: complete formal test lists/results, targeted mutation assertions, source-bound validation and JSON/HTML measurements. Each environment performs 18 trials and 1,080 per-trial event deliveries.
- `linux-runtime.json`, raw image/container inspection logs: guest architecture/kernel, image ID, user, resource limits, mounts, networking, init and exit state.
- `report.html`: separate native and Linux-in-VM tables. No cross-OS speedup/RSS ratio.
- `original-digests.json`: pre-normalization hashes. Export replaces repo/home/temp/evidence paths and URL credentials, then rebinds changed log hashes and validates the exported copy. It is a consistency receipt, not a signed independent attestation.

No environments, source build contexts, downloaded archives, VM disks, live spools or container images are exported. VM disks/images and verified toolchain caches deliberately remain local for reuse; successful cleanup means the owned workload/container is gone and the owned VM is stopped, not that all cache storage is erased. Failed exports remove their partial tree (also Git-ignored) and never replace an existing retained target. Raw failed runs stay under ignored local output; a failed run is not promoted to the retained success directory.

## Interpretation

The reviewed retained run executes **60 identical tests and five mutations per environment**, plus 36 trials / 2,160 matching committed effects in total. Native and Linux results are different environments, not an OS-performance comparison: SQLite versions differ (3.53.1 vs 3.40.1), visible host CPUs differ from the 4-vCPU guest, and storage/fsync/allocator accounting differs. Both use Python 3.12.14 and psutil 7.0.0. This host is ARM64; Intel assets are pinned but not exercised here.

RSS is the relay process's sampled resident memory during the experiment; Linux RSS is inside the guest/container and excludes host VM overhead. DB/WAL/SHM values are apparent file lengths, not filesystem allocation, bytes written or host VM-disk growth. The first process starts before measurement; restart startup is inside the window. Short peaks can be missed despite coverage/gap checks. VM configured RAM is not measured host VM RSS. Unrelated host load is uncontrolled.

Both environments verify process-crash recovery and transactional admission; neither establishes physical power-cut safety or a hard filesystem quota. Linux VM results do not establish native bare-metal Linux performance. Local validation is independent of GitHub billing and does not change repository visibility or imply a remote CI pass.
