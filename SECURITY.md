# Security boundary

Experimental, single-host software for trusted local producers and an operator-configured downstream. Both relay and demo receiver bind to `127.0.0.1`; neither offers authentication. Do not expose either port through a reverse proxy or on an untrusted network without authentication, TLS and a separate deployment review. `/control` on the demo receiver intentionally injects faults and is not a production endpoint.

Only the operator sets the downstream URL. Events cannot select a destination. The relay does not follow redirects. HTTPS uses Python's default certificate verification; HTTP is plaintext. Do not put credentials in the URL; authenticated upstream headers are outside this MVP. Restrict the data directory to the service account and use local storage with working file locks. Network filesystems, shared data directories and hostile local users are outside the supported boundary.

Payloads persist in plaintext until delivery. Delivered payloads are cleared logically, not securely erased: SQLite free pages, WAL, snapshots and backups may retain bytes. Receipt hashes, IDs and timestamps remain until retention pruning. IDs are not secrets. Process counters reset on restart.

Queue admission limits are not an operating-system quota or total process memory limit. Keep monitoring free space; actual I/O failure causes rejection or retry, not silent dropping. SQLite corruption recovery, encryption, disk-device failure and power-cut durability have not been tested. Preserve database/WAL consistency when taking backups; copying a live main DB alone is unsafe.

HTTP attempts have a socket timeout and a watchdog that closes established sockets at the configured deadline. OS hostname resolution can outlive that deadline and delay shutdown; use a numeric IP for a strictly local MVP deployment. This is not a hardened Internet HTTP server.

For security concerns, contact the repository owner privately; do not publish sensitive payloads or credentials in issues.
