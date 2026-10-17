# Current native macOS validation

Copied from `reviews/local-validation-startup/native/`: 61 tests, five targeted mutations and 18 real trials / 1,080 matching event effects. The combined cross-platform receipt binds both environments to the same source/test list and planned workload. Linux guest results are separate.

```sh
.venv/bin/python -m tools.check_validation results/native-macos
.venv/bin/python -m tools.check_local reviews/local-validation-startup
```

RSS covers sampled relay-process memory only; disk values are apparent DB/WAL/SHM lengths. The records do not establish power-cut durability or maximum throughput.
