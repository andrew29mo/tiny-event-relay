# Public release verification (2026-10-17)

Repository: [andrew29mo/tiny-event-relay](https://github.com/andrew29mo/tiny-event-relay). Visibility changed to Public with the owner's explicit authorization. Original project material remains MIT; third-party components retain their terms. No collaborators were added.

## Code, documents and evidence

- GitHub recognizes MIT. Initial-publication anonymous requests returned HTTP 200 for the repository, README, LICENSE and combined local-validation receipt, with file bytes identical to that checkout. `anonymous-read.json` preserves those initial-publication hashes. README and current evidence were subsequently updated for the startup fix; that historical anonymous-read receipt is not presented as a hash of the later README. Current public files are checked again after the final upload.
- Both environments use the same runtime/test source, complete test-ID list, payloads and planned arrivals. macOS and Colima Linux each passed 61 formal tests, five targeted mutations and 18 real trials / 1,080 matching per-trial event effects. No completed trial was omitted. Container removed, dedicated VM stopped.
- Current evidence is under `../local-validation-startup/`, with a duplicate native result under `../../results/native-macos/`. Tables were regenerated from current raw summaries; native and VM data remain separate. Guest RSS excludes host VM overhead, and disk measurements are apparent DB-family file lengths.
- Licensing documents were decoupled from transient repository visibility. Historical MIT-adoption/review records remain explicitly historical; their old source-bound receipts were not relabeled as current.
- Before visibility changed, 239 reachable historical blobs and 347 current candidate files were pattern-checked for personal absolute paths, common GitHub/AWS credentials and private-key headers; no matches were found. Environments, VM/toolchain files, databases, wheels, build output and personal guidance remain ignored. Pattern scanning is not an exhaustive secret audit.

```sh
.venv/bin/python -m tools.check_local reviews/local-validation-startup
.venv/bin/python -m tools.check_validation results/native-macos
```

The hosted macOS startup follow-up removes an unnecessary reverse-DNS dependency from the formal loopback server. See [the diagnosis and red/green regression evidence](../public-startup-fix/README.md). The current 61-test records supersede the initial 60-test publication receipts; the failed hosted runs remain historical.

## Actual public security settings

`security-settings.json` contains the configuration read back from GitHub, including rule IDs and timestamp:

- Secret scanning and push protection enabled. Private vulnerability reporting enabled.
- Dependabot security updates enabled/unpaused; vulnerability alerts enabled. Weekly pip and Actions version-update configuration is committed.
- Actions allow only checkout/setup-python and require full SHA pins; token defaults to read; workflow review approval is disabled. All external contributors require workflow approval. No repository secrets or variables were configured at the check.
- Main deletion and non-fast-forward updates are prohibited, with no bypass actors. A separate active rule requires `test (ubuntu-latest)` and `test (macos-latest)` from GitHub Actions. Repository admins may bypass only this CI rule, preserving direct single-maintainer work. No second reviewer or additional collaborator is required/granted.
- Only the owner `andrew29mo` appears in the collaborator list. Public readers can clone/fork and propose contributions; they do not gain write access to the original main branch.

These are configuration observations, not attempted destructive force-push/delete tests or proof of complete vulnerability detection. The owner can change settings. Scanning may continue asynchronously. Repository protections do not supply authentication or production readiness for the loopback HTTP service.

The [formal CI workflow](https://github.com/andrew29mo/tiny-event-relay/actions/workflows/ci.yml) is checked separately for the latest public commit; earlier Private zero-step billing failures remain historical. A local pass or Dependency Graph background job is not a formal remote CI pass.
