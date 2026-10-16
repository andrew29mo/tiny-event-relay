"""Check retained raw receipts, recomputed metrics, coverage and rendered output."""
import argparse
import hashlib
import json
import math
from pathlib import Path

from .benchmark import summarize,aggregate,render,check_sampling
from .evidence import source_manifest


def require(value,message):
    if not value:
        raise ValueError(message)


def check(report,*,current_source=True):
    require(report.get("schema")==2,"unsupported report schema")
    require(report["status"]=="passed","report did not finish successfully")
    if current_source:
        require(report["source"]==source_manifest(),"report does not describe current source")
    parameters = report["parameters"]
    count,rate,repeats = parameters["count"],parameters["rate"],parameters["repeats"]
    require(type(count) is int and 2<=count<=400 and type(repeats) is int and repeats>=1
            and isinstance(rate,(int,float)) and not isinstance(rate,bool) and math.isfinite(rate) and 0<rate<=10000,
            "invalid workload parameters")
    expected = {(scenario,size,repeat) for repeat in range(repeats) for scenario in ("normal","outage","restart") for size in (256,16384)}
    actual = [(t["scenario"],t["blob_bytes"],t["repeat"]) for t in report["trials"]]
    require(len(actual)==len(expected) and set(actual)==expected,"trial coverage mismatch")
    for t in report["trials"]:
        require(t["count"]==count and t["rate_per_s"]==rate,"workload changed")
        argv = t["relay_cli_args"]
        for flag,value in (("--timeout",.3),("--retry-base",.05),("--retry-cap",.2)):
            require(argv.count(flag)==1 and float(argv[argv.index(flag)+1])==value,"relay configuration mismatch")
        rows = t["records"]
        require(len(rows)==count,"incorrect request count")
        effects = t["receiver_receipt"]["effects"]
        require(len(effects)==count,"duplicate or missing business effects")
        receipt = {e["id"]:e for e in effects}
        require(set(receipt)=={f"event-{i:05}" for i in range(count)},"sink ID mismatch")
        for i,row in enumerate(rows):
            event_id = f"event-{i:05}"
            # Independent standard-library reference, never the serializer under test.
            payload = json.dumps({"sequence":i,"blob":"x"*t["blob_bytes"]},sort_keys=True,
                                 separators=(",",":"),ensure_ascii=True,allow_nan=False).encode()
            require(row["id"]==event_id and row["status"]==202 and row["duplicate"] is False,"acceptance mismatch")
            require(row["digest"]==receipt[event_id]["digest"]==hashlib.sha256(payload).hexdigest(),"payload mismatch")
            require(row["canonical_bytes"]==len(payload),"payload size mismatch")
            require(row["scheduled_s"]==i/rate,"planned schedule mismatch")
            require(row["acknowledged_s"]>=row["invoked_s"]>=row["scheduled_s"],"invalid arrival/accept timing")
            require(row["delivery_attempts"]==t["receiver_receipt"]["attempts"][event_id]>=1,"attempt receipt mismatch")
            require(receipt[event_id]["committed"] is not None,"missing post-commit observation")
            require(receipt[event_id]["committed_monotonic"] is not None,"missing post-commit observation")
            require(row["applied_s"]==receipt[event_id]["committed_monotonic"]-t["monotonic_start"],"effect timestamp mismatch")
            require(row["invoked_s"]<=row["applied_s"]<=t["completed_s"],"effect outside measurement window")
        require(t["final_snapshot"]["states"]=={"delivered":count},"not all events delivered")
        require(t["final_snapshot"]["retained_payload_bytes"]==0,"payloads remain unresolved")
        require(t["final_snapshot"]["worker_error"] is None,"worker error")
        samples = t["samples"]
        require(len(samples)>1 and all(b["elapsed_s"]>=a["elapsed_s"] for a,b in zip(samples,samples[1:])),"invalid samples")
        require(all(s[k]>=0 for s in samples for k in ("database_bytes","wal_bytes","shm_bytes")),"negative disk sizes")
        require(all(s["relay_rss_bytes"] is None or s["relay_rss_bytes"]>=0 for s in samples),"negative RSS")
        check_sampling(t)
        if t["scenario"]!="normal":
            states = t["backlog_snapshot"]["states"]
            require(states.get("pending",0)+states.get("in_flight",0)==count,"missing offline backlog")
            require(t["resume_s"]>max(r["acknowledged_s"] for r in rows),"invalid resume boundary")
            require(max(r["applied_s"] for r in rows)>t["resume_s"],"invalid drain boundary")
        require(summarize(t)==t["summary"],"summary not derived from raw data")
    require(aggregate(report)==report["aggregate"],"aggregate mismatch")
    # Reject NaN/Infinity anywhere, including metrics not rendered in HTML.
    json.dumps(report,allow_nan=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory",type=Path)
    args = parser.parse_args()
    report = json.loads((args.directory/"report.json").read_text())
    check(report)
    require((args.directory/"report.html").read_text()==render(report),"HTML disagrees with JSON")
    print(f"verified {len(report['trials'])} trials and {sum(len(t['records']) for t in report['trials'])} unique effects")


if __name__=="__main__":
    main()
