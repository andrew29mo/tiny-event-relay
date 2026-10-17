# Security boundary

Experimental, single-host software for trusted local producers and an operator-configured downstream. Both relay and demo receiver bind to `127.0.0.1`; neither offers authentication. Do not expose either port through a reverse proxy or on an untrusted network without authentication, TLS and a separate deployment review. `/control` on the demo receiver intentionally injects faults and is not a production endpoint.

Both HTTP endpoints require one matching `127.0.0.1:<port>` or `localhost:<port>` Host, reject Origin headers and reject cross-site Fetch Metadata. This narrows browser-origin/DNS-rebinding access; it is not authentication against other local programs, which can choose their headers. Browser frontends/CORS and alternate proxy Host values are outside this CLI-only MVP.

Only the operator sets the downstream URL. Events cannot select a destination. The relay does not follow redirects. HTTPS uses Python's default certificate verification; HTTP is plaintext. Do not put credentials in the URL; authenticated upstream headers are outside this MVP. Restrict the data directory to the service account and use local storage with working file locks. Network filesystems, shared data directories and hostile local users are outside the supported boundary.

Payloads persist in plaintext until delivery. Delivered payloads are cleared logically, not securely erased: SQLite free pages, WAL, snapshots and backups may retain bytes. Receipt hashes, IDs and timestamps remain until retention pruning. IDs are not secrets. Process counters reset on restart.

Queue admission limits are not an operating-system quota or total process memory limit. Keep monitoring free space; actual I/O failure causes rejection or retry, not silent dropping. SQLite corruption recovery, encryption, disk-device failure and power-cut durability have not been tested. Preserve database/WAL consistency when taking backups; copying a live main DB alone is unsafe.

HTTP attempts have a socket timeout and a watchdog that closes established sockets at the configured deadline. OS hostname resolution can outlive that deadline and delay shutdown; use a numeric IP for a strictly local MVP deployment. This is not a hardened Internet HTTP server.

For security concerns, use **Report a vulnerability** in the repository’s [Security tab](https://github.com/andrew29mo/tiny-event-relay/security). Private vulnerability reporting is enabled. Do not publish sensitive payloads or credentials in issues.

## Repository protections

The public repository uses secret scanning and push protection, Dependabot alerts/security updates and weekly pip/Actions version checks. Actions are limited to checkout/setup-python with full commit SHA pinning, a read-only default token, no PR-review approval permission, and approval required for all external contributors. The workflow does not use `pull_request_target` or persist checkout credentials.

Active main rules forbid deletion and force-push with no bypass. A separate rule requires the two GitHub Actions OS checks; repository administrators may bypass that CI rule to preserve the solo-maintainer workflow. No mandatory second reviewer is configured. This is an explicit maintainer exception, not a claim that every direct maintainer push is gated by completed CI. Only the owner has repository collaborator access at the release check. Administrators can change repository settings; these controls are not immutable.

See the timestamped [public release check](reviews/public-release/README.md) for the read-back configuration. Scanner coverage is limited to supported patterns; enabling scanning does not prove that every possible secret or vulnerability is absent. These repository controls do not change the local-service authentication/deployment boundaries above.
