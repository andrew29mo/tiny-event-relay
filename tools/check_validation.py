"""Validate actual source/test coverage, command outcomes and retained log hashes."""
import argparse
import hashlib
import json
import unittest
from pathlib import Path

from .check_report import require,check
from .benchmark import render
from .evidence import source_manifest
from .test_suite import ids
from .mutation_check import CASES


def check_validation(directory):
    directory = Path(directory)
    source = source_manifest()
    receipt = json.loads((directory/"validation.json").read_text())
    require(receipt["status"]=="passed" and receipt["source"]==source,"validation not passed for current source")
    expected_modules = ["tools.test_suite","tools.mutation_check","tools.benchmark","tools.check_report"]
    require([s["module_args"][0] for s in receipt["steps"]]==expected_modules,"validation steps mismatch")
    for i,step in enumerate(receipt["steps"],1):
        require(step["passed"] and step["exit_code"]==0 and not step["timed_out"] and not step["interrupted"]
                and step["cleanup_required"]==0 and step["cleanup_complete"],"failed or incompletely cleaned validation step")
        require(hashlib.sha256((directory/f"step-{i}.txt").read_bytes()).hexdigest()==step["log_sha256"],"step log changed")
    tests = json.loads((directory/"tests/tests.json").read_text())
    loader = unittest.TestLoader()
    expected = sorted(ids(loader.discover("tests")))
    require(expected and not loader.errors and tests["passed"] and tests["source"]==source,"invalid test receipt")
    require(expected==tests["expected"]==sorted(tests["started"])==sorted(tests["successes"])
            and not tests["failures"] and not tests["errors"] and not tests["skips"],"missing/failed/skipped formal tests")
    require(hashlib.sha256((directory/"tests/tests.txt").read_bytes()).hexdigest()==tests["log_sha256"],"test log changed")
    mutation = json.loads((directory/"mutations/mutations.json").read_text())
    require(mutation["passed"] and mutation["source"]==source and len(mutation["cases"])==len(CASES),"mutation receipt mismatch")
    require({m["name"] for m in mutation["cases"]}=={c[0] for c in CASES},"missing mutation")
    for m in mutation["cases"]:
        require(m["detected"] and m["exit_code"]==1 and m["failures"]==1 and m["errors"]==0,"mutation not detected by assertion")
        text = (directory/"mutations"/(m["name"]+".txt")).read_text()
        require("AssertionError" in text and "FAILED (failures=1)" in text,"missing mutation failure evidence")
    report = json.loads((directory/"benchmark/report.json").read_text())
    check(report)
    require((directory/"benchmark/report.html").read_text()==render(report),"HTML disagrees with raw report")
    return {"tests":len(expected),"trials":len(report["trials"]),"mutations":len(CASES)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory",type=Path)
    args = parser.parse_args()
    print(json.dumps(check_validation(args.directory)))


if __name__=="__main__":
    main()
