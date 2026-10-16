"""Real-process loopback experiments; no simulated latency or RSS values."""
import argparse
import hashlib
import html
import json
import platform
import random
import statistics
import sys
import tempfile
import threading
import time
from collections import defaultdict
from datetime import datetime,timezone
from pathlib import Path

import psutil

from relay.httpio import json_request
from relay.service import canonical
from tests.support import Stack,wait_for
from .evidence import source_manifest


def percentile(values,p):
    ordered = sorted(values)
    import math
    return ordered[max(0,math.ceil(len(ordered)*p)-1)]


class Sampler:
    def __init__(self,stack):
        self.stack = stack
        self.stop = threading.Event()
        self.samples = []
        self.thread = threading.Thread(target=self.run)

    def run(self):
        start = time.monotonic()
        while not self.stop.is_set():
            child = self.stack.relay
            rss = None
            pid = child.process.pid if child else None
            if pid:
                try:
                    rss = psutil.Process(pid).memory_info().rss
                except psutil.NoSuchProcess:
                    pass
            directory = self.stack.directory/"queue"
            sizes = {}
            for suffix in ("","-wal","-shm"):
                try:
                    sizes[suffix] = (directory/("queue.sqlite"+suffix)).stat().st_size
                except FileNotFoundError:
                    sizes[suffix] = 0
            self.samples.append({"elapsed_s":time.monotonic()-start,"pid":pid,"relay_rss_bytes":rss,
                                 "database_bytes":sizes[""],"wal_bytes":sizes["-wal"],"shm_bytes":sizes["-shm"]})
            self.stop.wait(.01)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self,*_):
        self.stop.set()
        self.thread.join()
        if not self.samples:
            raise AssertionError("no memory/disk samples collected")


def trial(scenario,blob_bytes,number,*,count,rate):
    with tempfile.TemporaryDirectory() as directory:
        stack = Stack(directory)
        sampler = Sampler(stack)
        try:
            stack.start()
            stack.control("ok",.003)
            if scenario!="normal":
                stack.sink.stop()  # Real absent listener, not a fabricated response time.
            payloads = [{"sequence":i,"blob":"x"*blob_bytes} for i in range(count)]
            with sampler:
                mono_start,wall_start = time.monotonic(),time.time()
                records = []
                for i,payload in enumerate(payloads):
                    scheduled = i/rate
                    time.sleep(max(0,mono_start+scheduled-time.monotonic()))
                    invoked = time.monotonic()-mono_start
                    status,response = stack.submit(f"event-{i:05}",payload)
                    ack = time.monotonic()-mono_start
                    records.append({"id":f"event-{i:05}","scheduled_s":scheduled,"invoked_s":invoked,
                                    "acknowledged_s":ack,"status":status,"duplicate":response.get("duplicate"),
                                    "digest":hashlib.sha256(canonical(payload)).hexdigest(),
                                    "canonical_bytes":len(canonical(payload))})
                    if status!=202 or response.get("duplicate") is not False:
                        raise AssertionError("experiment submission was not newly accepted")
                backlog = json_request(stack.url+"/v1/stats")[1]
                resume = None
                if scenario!="normal":
                    time.sleep(.2)
                    if scenario=="restart":
                        stack.relay.stop(kill=True)
                        stack.start_relay()
                    # Timestamp before sink readiness, so drain time includes startup.
                    resume = time.monotonic()-mono_start
                    stack.start_sink(delay=.003)
                wait_for(lambda: json_request(stack.url+"/v1/stats")[1]["states"].get("delivered",0)==count,timeout=30)
                effects = stack.effects()
                final = json_request(stack.url+"/v1/stats")[1]
                end = time.monotonic()-mono_start
                wall_drift = (time.time()-wall_start)-end
                if abs(wall_drift)>.02:
                    raise AssertionError("wall clock changed during cross-process timing")
                actual = {e["id"]:e for e in effects["effects"]}
                if len(effects["effects"])!=count or set(actual)!={r["id"] for r in records}:
                    raise AssertionError("missing or unexpected business effects")
                for r in records:
                    effect = actual[r["id"]]
                    if effect["digest"]!=r["digest"]:
                        raise AssertionError("payload digest mismatch")
                    if effect["committed"] is None:
                        raise AssertionError("missing post-commit observation")
                    r["applied_s"] = effect["committed"]-wall_start
                    r["delivery_attempts"] = effects["attempts"][r["id"]]
                    if r["applied_s"]<r["invoked_s"]-.02:
                        raise AssertionError("inconsistent effect timestamp")
                if final["retained_payload_bytes"]!=0 or final["worker_error"]:
                    raise AssertionError("unresolved storage state after drain")
            if sampler.thread.is_alive():
                raise AssertionError("sampler did not stop")
            if scenario!="normal" and backlog["states"].get("pending",0)+backlog["states"].get("in_flight",0)!=count:
                raise AssertionError("offline backlog is incomplete")
            result = {"scenario":scenario,"blob_bytes":blob_bytes,"repeat":number,"count":count,"rate_per_s":rate,
                      "sink_response_delay_s":.003,"records":records,"samples":sampler.samples,
                      "backlog_snapshot":backlog,"final_snapshot":final,"resume_s":resume,
                      "receiver_receipt":effects,"wall_start":wall_start,
                      "relay_cli_args":[arg.replace(str(directory),"<trial-dir>") for arg in stack.relay_args],
                      "wall_clock_drift_s":wall_drift,"completed_s":end}
            result["summary"] = summarize(result)
            return result
        finally:
            stack.close()


def summarize(t):
    rows,samples = t["records"],t["samples"]
    first = min(r["invoked_s"] for r in rows)
    last = max(r["applied_s"] for r in rows)
    latency = [1000*(r["acknowledged_s"]-r["invoked_s"]) for r in rows]
    e2e = [1000*(r["applied_s"]-r["invoked_s"]) for r in rows]
    rss = [s["relay_rss_bytes"] for s in samples if s["relay_rss_bytes"] is not None]
    if not rss:
        raise AssertionError("no relay RSS samples")
    return {"accepted":len(rows),"unique_effects":len(rows),
            "accept_p50_ms":percentile(latency,.5),"accept_p95_ms":percentile(latency,.95),
            "effect_p50_ms":percentile(e2e,.5),"effect_p95_ms":percentile(e2e,.95),
            "unique_effects_per_s":len(rows)/(last-first),
            "drain_s":last-t["resume_s"] if t["resume_s"] is not None else None,
            "max_issue_lag_ms":1000*max(r["invoked_s"]-r["scheduled_s"] for r in rows),
            "peak_relay_rss_bytes":max(rss),
            "peak_database_family_bytes":max(s["database_bytes"]+s["wal_bytes"]+s["shm_bytes"] for s in samples),
            "max_sample_gap_ms":1000*max((b["elapsed_s"]-a["elapsed_s"] for a,b in zip(samples,samples[1:])),default=0)}


def aggregate(report):
    groups = defaultdict(list)
    for trial in report["trials"]:
        groups[(trial["scenario"],trial["blob_bytes"])].append(trial["summary"])
    return [{"scenario":scenario,"blob_bytes":size,"trials":len(rows),
             "median_of_trial_summaries":{key:statistics.median(r[key] for r in rows) if rows[0][key] is not None else None for key in rows[0]}}
            for (scenario,size),rows in sorted(groups.items())]


def render(report):
    rows = []
    for group in report["aggregate"]:
        s = group["median_of_trial_summaries"]
        values = [group["scenario"],group["blob_bytes"],f'{s["accept_p95_ms"]:.2f}',f'{s["effect_p95_ms"]:.2f}',
                  f'{s["unique_effects_per_s"]:.1f}',f'{s["peak_relay_rss_bytes"]/1048576:.2f}',
                  f'{s["peak_database_family_bytes"]/1048576:.2f}',f'{s["drain_s"]:.2f}' if s["drain_s"] is not None else "—"]
        rows.append("<tr>"+"".join("<td>"+html.escape(str(v))+"</td>" for v in values)+"</tr>")
    return """<!doctype html><html lang="en"><meta charset="utf-8"><title>tiny-event-relay measurements</title>
<style>body{font:16px system-ui;max-width:1100px;margin:40px auto;padding:0 20px;color:#183044}table{border-collapse:collapse;width:100%}td,th{border:1px solid #cbd5df;padding:9px;text-align:left}th{background:#edf3f7}code{overflow-wrap:anywhere}</style>
<h1>tiny-event-relay: retained measurements</h1><p>Real production CLI, separate local receiver process; fresh durable database per trial. Medians of trial summaries, not pooled percentiles.</p>
<p>"""+html.escape(report["environment"]["platform"])+"; Python "+html.escape(report["environment"]["python"])+"</p>"+"""<table><thead><tr><th>Scenario</th><th>Blob bytes</th><th>Accept p95 ms</th><th>Effect p95 ms</th><th>Unique effects/s</th><th>Relay RSS MiB</th><th>DB+WAL+SHM MiB</th><th>Drain s</th></tr></thead><tbody>"""+"".join(rows)+"</tbody></table><h2>Interpretation and limits</h2><ul>"+"".join("<li>"+html.escape(item)+"</li>" for item in report["limitations"])+"</ul><p>Source SHA-256: <code>"+report["source"]["sha256"]+"</code></p></html>\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,default=Path("results/local/benchmark"))
    parser.add_argument("--count",type=int,default=60)
    parser.add_argument("--rate",type=float,default=15)
    parser.add_argument("--repeats",type=int,default=3)
    parser.add_argument("--execution-label",default="unspecified; operator must identify host or VM")
    args = parser.parse_args()
    if args.count<2 or args.count>400 or not 0<args.rate<=10000 or args.repeats<1:
        parser.error("count 2..400, finite rate 0..10000, repeats >=1 required")
    if args.output.exists():
        parser.error("output must be a fresh directory")
    before = source_manifest()
    args.output.mkdir(parents=True)
    report = {"schema":1,"status":"running","created_utc":datetime.now(timezone.utc).isoformat(),"source":before,
              "environment":{"platform":platform.system()+" "+platform.release()+" "+platform.machine(),
                             "python":platform.python_version(),"sqlite":__import__("sqlite3").sqlite_version,"psutil":psutil.__version__,
                             "execution":args.execution_label,"cpu_count":os_cpu_count()},
              "parameters":{"count":args.count,"rate":args.rate,"repeats":args.repeats,"seed":417},
              "limitations":["Fixed scheduled load, not a maximum-throughput or comparative speedup claim; no nondurable baseline.",
                "Formal relay CLI uses a 0.3 s timeout, 0.05 s retry base and 0.2 s retry cap for bounded experiments, rather than deployment defaults; raw CLI arguments are retained per trial.",
                "Sequential issuer records actual issue lag; the same planned offsets and payloads are reused in every scenario.",
                "Offline scenarios stop the actual receiver before arrivals; restart additionally SIGKILLs and restarts the relay after all accepted submissions.",
                "The receiver uses a configured 3 ms response delay from process startup on recovery too. Drain includes receiver startup.",
                "Endpoint: transactional application of unique effects at demo sink; relay acknowledgment of sink response can occur later.",
                "RSS samples every nominal 10 ms cover relay PID only (both PID lifetimes on restart), excluding receiver/client/kernel and filesystem cache.",
                "Disk samples count apparent DB+WAL+SHM file lengths, not allocated filesystem blocks, total host writes or storage endurance; short peaks may be missed.",
                "No power-loss, disk hardware, hostile network, Internet, Linux or multi-node validation in this native report.",
                "At-least-once transport requires a receiver that atomically deduplicates IDs and applies its effects; no universal exactly-once guarantee."],
              "trials":[]}
    try:
        for repeat in range(args.repeats):
            cases = [(scenario,size) for scenario in ("normal","outage","restart") for size in (256,16384)]
            random.Random(417+repeat).shuffle(cases)
            for scenario,size in cases:
                print(f"trial {repeat+1}/{args.repeats}: {scenario}, blob={size}",flush=True)
                report["trials"].append(trial(scenario,size,repeat,count=args.count,rate=args.rate))
                (args.output/"report.json").write_text(json.dumps(report,indent=2)+"\n")
        if source_manifest()!=before:
            raise AssertionError("source changed during benchmark")
        report["aggregate"] = aggregate(report)
        report["status"] = "passed"
        (args.output/"report.json").write_text(json.dumps(report,indent=2)+"\n")
        (args.output/"report.html").write_text(render(report))
    except BaseException:
        report["status"] = "failed"
        (args.output/"report.json").write_text(json.dumps(report,indent=2)+"\n")
        raise


def os_cpu_count():
    import os
    return os.cpu_count()


if __name__=="__main__":
    main()
