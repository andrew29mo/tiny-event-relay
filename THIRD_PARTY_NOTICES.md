# Third-party components and license status

No project license has been selected. This is a private MVP; public release requires a separate license decision.

The relay has no third-party runtime Python dependencies. It uses Python's standard library, including the bundled SQLite library. Python and SQLite retain their own terms; this repository does not redistribute their binaries.

Development measurements use **psutil 7.0.0**, BSD-3-Clause, installed separately through `requirements-dev.txt`. See the [versioned upstream license](https://github.com/giampaolo/psutil/blob/release-7.0.0/LICENSE). No psutil source or wheels are vendored.

Packaging uses setuptools as a build dependency. CI references GitHub-maintained checkout and setup-python actions pinned by commit. These tools retain their respective upstream licenses; their code is not copied into this repository. The demo receiver and synthetic payloads are original project code/data. No external models or datasets are included.
