# Historical MIT-adoption receipt (6d05ff7)

This records the license adoption while the repository was Private. Public visibility was separately authorized later; current evidence is in `../local-validation-public/`. The MIT grant remains unchanged.

# MIT adoption (2026-10-17)

The owner selected MIT for original tiny-event-relay code, documentation and synthetic event data. Copyright (c) 2026 Andrew Yuan. Repository visibility remains Private; no collaborator or access grant is added.

- `LICENSE` contains the complete MIT grant and disclaimer.
- README identifies MIT and keeps experimental/runtime limitations intact.
- `pyproject.toml` uses the SPDX expression `MIT` and includes `LICENSE` and `THIRD_PARTY_NOTICES.md` in distributions. Build backend minimum is setuptools 77.0.3, which supports this metadata format.
- [Third-party notices](../../THIRD_PARTY_NOTICES.md) distinguish standard-library runtime, separately installed development dependencies, optional host/VM tools and CI actions. Versioned upstream licenses were checked: psutil 7.0.0 BSD-3-Clause, Colima 0.10.3 MIT, Lima 2.2.1 Apache-2.0; setuptools and the pinned GitHub actions retain their MIT/bundled-component notices. Docker tools/image/OS components retain their respective terms. No third-party binaries, VM images or vendored runtime implementation are distributed by the project wheel.
- Maintainer-authored tooling adapted from tiny-dns-router is covered by the original project's MIT grant. No external model or dataset is included.

## Actual package checks

`packaging.json` records the actual wheel hash, build generator, exact included license-file hashes and runtime file hashes. The wheel declares `License-Expression: MIT`, includes both license/notice files byte-for-byte, includes exactly the checked-out `relay/*.py` implementation, and has no external runtime requirement. It was installed without dependencies into an ignored isolated environment; the installed console entry point returned help successfully from outside the source checkout. This does not publish a package or redistribute its build environment. Build tools, wheel and environments remain local/ignored.

## Source-bound validation

The metadata edit changes a formally hashed input. Both platforms therefore rerun the complete 60-test suite, five targeted mutations and 18 real measurement trials per environment. The combined snapshot also binds the MIT license and third-party notice files. See [the MIT-era validation](../local-validation-mit/README.md), [combined receipt](../local-validation-mit/combined.json) and its separate native/VM JSON/HTML reports. Old records remain explicitly historical rather than being relabeled as new-source measurements.

This licensing change does not establish new performance benefits or power-cut durability. Guest RSS excludes host VM overhead; disk numbers are apparent DB-family file lengths. Third-party obligations remain in force; the current no-vendoring/separately-installed arrangement does not require changing the original project's MIT grant. Bundling tools/images later would require its own component/license review. Public visibility remains a separate owner decision, and local success is not remote CI success.
