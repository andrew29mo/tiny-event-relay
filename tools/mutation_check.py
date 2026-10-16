"""Bounded mutations in isolated source copies; originals are never modified."""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .evidence import ROOT,source_manifest,sanitize


CASES = [
    ("payload-loss", "relay/service.py", [("def canonical(value):\n    return json.dumps",
      "def canonical(value):\n    if isinstance(value,dict) and 'b' in value:\n        value={k:v for k,v in value.items() if k!='b'}\n    return json.dumps")],
     "tests.test_relay.NetworkTests.test_canonical_delivery_and_duplicate_conflict"),
    ("count-quota", "relay/store.py", [("if count >= self.max_events or size + len(payload) > self.max_payload_bytes:","if False:")],
     "tests.test_relay.NetworkTests.test_count_quota_never_evicts_unresolved"),
    ("conflicting-id", "relay/store.py", [("if row[\"digest\"] != digest:","if False:")],
     "tests.test_relay.NetworkTests.test_canonical_delivery_and_duplicate_conflict"),
    ("stale-token", "relay/store.py", [("AND token=?\"\"\"","AND ? IS NOT NULL\"\"\"")],
     "tests.test_relay.StoreFaultTests.test_stale_claim_token_cannot_override_new_claim"),
    ("receiver-dedup", "tools/receiver.py", [("if old is None:\n                        sink.db.execute(\"INSERT INTO receipts", "if True:\n                        sink.db.execute(\"INSERT INTO receipts"),("INSERT INTO receipts VALUES (?,?)","INSERT OR IGNORE INTO receipts VALUES (?,?)")],
     "tests.test_relay.NetworkTests.test_lost_ack_retries_but_business_effect_once"),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must be fresh")
    args.output.mkdir(parents=True)
    before = source_manifest()
    receipts = []
    for name,file,replacements,test in CASES:
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory)
            for part in ("relay","tools","tests"):
                shutil.copytree(ROOT/part,copy/part,ignore=shutil.ignore_patterns("__pycache__"))
            for part in ("pyproject.toml","requirements-dev.txt"):
                shutil.copyfile(ROOT/part,copy/part)
            target = copy/file
            text = target.read_text()
            for old,new in replacements:
                if text.count(old)!=1:
                    raise AssertionError("mutation target is ambiguous: "+name)
                text = text.replace(old,new)
            target.write_text(text)
            result = subprocess.run([sys.executable,"-m","tools.test_suite","--output",str(copy/"receipt"),test],
                                    cwd=copy,capture_output=True,text=True,timeout=25)
            receipt = json.loads((copy/"receipt/tests.json").read_text())
            # A timeout, import error or setup error does not count as a detected behavior mutation.
            detected = result.returncode==1 and receipt["failures"]==1 and receipt["errors"]==0 and receipt["started"]==[test]
            log = sanitize(result.stdout+result.stderr).replace(str(copy),"<mutation-copy>")
            (args.output/(name+".txt")).write_text(log)
            receipts.append({"name":name,"file":file,"replacements":replacements,"test":test,"detected":detected,
                             "exit_code":result.returncode,"failures":receipt["failures"],"errors":receipt["errors"]})
    passed = all(r["detected"] for r in receipts) and before==source_manifest()
    (args.output/"mutations.json").write_text(json.dumps({"passed":passed,"source":before,"cases":receipts},indent=2)+"\n")
    print(json.dumps(receipts,indent=2))
    raise SystemExit(0 if passed else 1)


if __name__=="__main__":
    main()
