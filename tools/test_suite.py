"""Machine-readable unittest evidence; skips, missing tests and errors fail validation."""
import argparse
import hashlib
import io
import json
import sys
import unittest
from pathlib import Path

from .evidence import source_manifest,sanitize


def ids(suite):
    for item in suite:
        if isinstance(item,unittest.TestSuite):
            yield from ids(item)
        else:
            yield item.id()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("names",nargs="*")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must be fresh")
    args.output.mkdir(parents=True)
    before = source_manifest()
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromNames(args.names) if args.names else loader.discover("tests")
    expected = sorted(ids(suite))
    successes,started = [],[]
    class Result(unittest.TextTestResult):
        def startTest(self,test):
            started.append(test.id())
            super().startTest(test)
        def addSuccess(self,test):
            successes.append(test.id())
            super().addSuccess(test)
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream,verbosity=2,resultclass=Result).run(suite)
    log = sanitize(stream.getvalue())
    (args.output/"tests.txt").write_text(log)
    passed = (bool(expected) and not loader.errors and result.wasSuccessful() and not result.skipped
              and expected==sorted(started)==sorted(successes) and len(set(expected))==len(expected)
              and before==source_manifest())
    receipt = {"passed":passed,"source":before,"expected":expected,"started":started,"successes":successes,
               "failures":len(result.failures),"errors":len(result.errors),"skips":len(result.skipped),
               "log_sha256":hashlib.sha256(log.encode()).hexdigest()}
    (args.output/"tests.json").write_text(json.dumps(receipt,indent=2)+"\n")
    print(log,end="")
    raise SystemExit(0 if passed else 1)


if __name__=="__main__":
    main()
