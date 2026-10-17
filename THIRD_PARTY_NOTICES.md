# Third-party components and license status

No project license has been selected. This is a private MVP; public release requires a separate license decision.

The relay has no third-party runtime Python dependencies. It uses Python's standard library, including the bundled SQLite library. Python and SQLite retain their own terms; this repository does not redistribute their binaries.

Development measurements use **psutil 7.0.0**, BSD-3-Clause, installed separately through `requirements-dev.txt`. See the [versioned upstream license](https://github.com/giampaolo/psutil/blob/release-7.0.0/LICENSE). No psutil source or wheels are vendored.

Packaging uses setuptools as a build dependency. CI references GitHub-maintained checkout and setup-python actions pinned by commit. These tools retain their respective upstream licenses; their code is not copied into this repository. The demo receiver and synthetic payloads are original project code/data. No external models or datasets are included.

Local Linux validation downloads **Colima 0.10.3** ([MIT](https://github.com/abiosoft/colima/blob/v0.10.3/LICENSE)) and **Lima 2.2.1** ([Apache-2.0](https://github.com/lima-vm/lima/blob/v2.2.1/LICENSE)) from official releases, with pinned SHA-256 digests. It reuses an installed Docker CLI/buildx and builds a pinned official Python 3.12.14 Debian-based image locally. These tools, the image and its OS components retain their own licenses; no downloaded binaries, images, VM disks or environments are committed. The host controller adapts maintainer-authored validation tooling previously used in tiny-dns-router; this does not select an open-source license for tiny-event-relay.
