# Project license and third-party components

Original tiny-event-relay code, documentation and synthetic test/benchmark data are licensed under [MIT](LICENSE), copyright (c) 2026 Andrew Yuan. Third-party software retains its own copyright, license and notices; this file does not relicense it.

## Runtime

The relay has no third-party runtime Python dependencies. Python and its standard library are subject to the [Python 3.12 license and included notices](https://docs.python.org/3.12/license.html). SQLite is [dedicated to the public domain by its authors](https://www.sqlite.org/copyright.html); Python distributions may include additional components governed by their respective terms. This repository and its project wheel do not redistribute Python or SQLite binaries.

## Development and packaging

| Component | Role | Upstream license / notices |
|---|---|---|
| psutil 7.0.0 | Separately installed measurement/validation dependency | [BSD-3-Clause](https://github.com/giampaolo/psutil/blob/release-7.0.0/LICENSE) |
| setuptools >=77.0.3 | Isolated build dependency; modern SPDX metadata support | [MIT](https://github.com/pypa/setuptools/blob/v77.0.3/LICENSE) and licenses of its vendored components |
| GitHub checkout / setup-python | CI actions pinned by commit in the workflow | [checkout MIT](https://github.com/actions/checkout/blob/fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09/LICENSE), [setup-python MIT](https://github.com/actions/setup-python/blob/ece7cb06caefa5fff74198d8649806c4678c61a1/LICENSE) and bundled-component notices |

No psutil wheels/source, build-tool code or action distributions are vendored in this repository or project wheel. When redistributing those components, retain their required copyright, license, disclaimer and other notices. BSD-3-Clause also restricts endorsement using the authors' names.

## Optional local Linux validation tools

| Component | Handling | Upstream terms |
|---|---|---|
| Colima 0.10.3 | Downloaded from official releases with pinned SHA-256 | [MIT](https://github.com/abiosoft/colima/blob/v0.10.3/LICENSE) |
| Lima 2.2.1 | Downloaded from official releases with pinned SHA-256 | [Apache-2.0](https://github.com/lima-vm/lima/blob/v2.2.1/LICENSE) and its distribution's third-party notices |
| Docker CLI / buildx | Reuse separately installed local tools | [Docker CLI Apache-2.0](https://github.com/docker/cli/blob/master/LICENSE), [buildx Apache-2.0](https://github.com/docker/buildx/blob/master/LICENSE) and bundled-component notices; Docker Desktop is a separate product with its own terms |
| Python 3.12.14 Debian-based container image | Built/downloaded locally from the pinned official image | Python's license, Debian package copyrights and all other included component licenses |

These are separately installed/executed tools, not MIT-relicensed project code. No downloaded binaries, container images, VM disks or environments are committed or included in the project wheel. Redistributing such an image/toolchain is a separate distribution with its own notice, source-offer and other obligations where applicable; the project's MIT file alone does not cover that distribution.

The host controller adapts maintainer-authored validation tooling previously used in tiny-dns-router. The demonstration receiver and synthetic event data are original project material. No external models or datasets are included.

## Compatibility scope

Review of the versioned upstream licenses and current repository contents found no requirement to change the original project's MIT license for this arrangement: standard-library runtime, separately installed development/tools, no vendored third-party implementation or binary distribution. Third-party notices and any redistribution obligations remain in force. This is a repository-specific review, not approval of every possible future bundled deployment.
