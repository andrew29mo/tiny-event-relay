# Historical 51-test native run (ce620dc)

Use that revision’s checker for these unchanged raw receipts. Current 60-test data is in `../native-macos/`.

# Current native macOS evidence

Exact duplicate of `reviews/local-validation/native`, produced from the same immutable source snapshot as the Linux container. The dedicated Colima VM was stopped during this phase. The complete receipts verify 51 formal tests, five targeted mutations and 18 measured trials (1,080 matching unique effects).

```sh
.venv/bin/python -m tools.check_validation results/native-macos
.venv/bin/python -m tools.check_local reviews/local-validation
```

Source identity and complete test IDs are checked across both environments; portable logs have path normalization and original digests are retained in the dual-platform evidence directory. Linux VM performance/RSS is separate and must not be interpreted as native Linux or as a cross-OS speedup. Root README and the dual-platform HTML show current results; previous snapshots are explicitly historical.
