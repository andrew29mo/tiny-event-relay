"""Sequential validation with bounded steps and inherited ownership-based child cleanup."""
import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime,timezone
from pathlib import Path

import psutil

from .evidence import ROOT,source_manifest,sanitize


def owned(tag):
    result = []
    for proc in psutil.process_iter(["pid"]):
        try:
            if tag in proc.environ().get("TINY_EVENT_VALIDATION_OWNERS","").split(":"):
                result.append(proc)
        except (psutil.NoSuchProcess,psutil.AccessDenied):
            pass
    return result


def run_step(args,output,timeout):
    tag = uuid.uuid4().hex
    chain = os.environ.get("TINY_EVENT_VALIDATION_OWNERS","")
    env = {**os.environ,"TINY_EVENT_VALIDATION_OWNERS":chain+":"+tag}
    start = time.monotonic()
    child = subprocess.Popen([sys.executable,"-m",*args],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                             start_new_session=True,text=True,errors="replace")
    timed_out,interrupted = False,False
    text = ""
    reclaimed = set()
    def cleanup():
        for _ in range(2):
            processes = owned(tag)
            for proc in processes:
                try:
                    reclaimed.add((proc.pid,proc.create_time()))
                    proc.kill()
                except psutil.NoSuchProcess:
                    pass
            psutil.wait_procs(processes,timeout=2)
            if not owned(tag):
                break
    try:
        text,_ = child.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
    except (KeyboardInterrupt,SystemExit):
        interrupted = True
    finally:
        # Also reclaim new-session/reparented children after successful parent exit.
        # Nested validators inherit the owner chain, so an outer timeout can reclaim them.
        cleanup()
        if child.poll() is None:
            child.kill()
        remaining_text,_ = child.communicate(timeout=5)
        if not text:
            text = remaining_text
    complete = not owned(tag)
    log = sanitize(text)
    output.write_text(log)
    return {"module_args":args,"exit_code":child.returncode,"timed_out":timed_out,"interrupted":interrupted,
            "cleanup_required":len(reclaimed),"cleanup_complete":complete,
            "duration_s":time.monotonic()-start,"log_sha256":hashlib.sha256(log.encode()).hexdigest(),
            "passed":not timed_out and not interrupted and not reclaimed and complete and child.returncode==0}


def main():
    def interrupt(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,interrupt)
    parser = argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,default=Path("results/local/validation"))
    parser.add_argument("--execution-label",default="unspecified; operator must identify host or VM")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must be a fresh directory")
    args.output.mkdir(parents=True)
    before = source_manifest()
    receipt = {"status":"running","created_utc":datetime.now(timezone.utc).isoformat(),"source":before,"steps":[]}
    def save():
        (args.output/"validation.json").write_text(json.dumps(receipt,indent=2)+"\n")
    save()
    steps = [(["tools.test_suite","--output",str(args.output/"tests")],180),
             (["tools.mutation_check","--output",str(args.output/"mutations")],120),
             (["tools.benchmark","--output",str(args.output/"benchmark"),"--execution-label",args.execution_label],300),
             (["tools.check_report",str(args.output/"benchmark")],20)]
    try:
        for i,(command,timeout) in enumerate(steps):
            print(f"step {i+1}/{len(steps)}: {command[0]}",flush=True)
            result = run_step(command,args.output/f"step-{i+1}.txt",timeout)
            # Keep receipts portable if the caller supplied an absolute output path.
            result["module_args"] = [sanitize(s) for s in result["module_args"]]
            receipt["steps"].append(result)
            save()
            if not result["passed"]:
                raise RuntimeError("validation step failed; see retained logs")
        if before!=source_manifest():
            raise RuntimeError("source changed during validation")
        receipt["status"] = "passed"
        save()
        from .check_validation import check_validation
        check_validation(args.output)
    except BaseException:
        receipt["status"] = "failed"
        save()
        raise


if __name__=="__main__":
    main()
