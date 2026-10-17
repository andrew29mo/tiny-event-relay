"""Verify same-source dual-platform evidence, isolation and actual exit/cleanup records."""
import argparse
import html
import json
from pathlib import Path

from .check_report import require
from .check_validation import check_validation
from .evidence import ROOT,source_manifest
from .platform_io import sha,fingerprint

SETUP = ("containers/validation.Dockerfile","tools/colima-lock.json","tools/validate-local")
ALIASES = {"arm64":"arm64","aarch64":"arm64","x86_64":"x86_64","amd64":"x86_64"}


def check_local(output,finalizing=False):
    output = Path(output)
    r = json.loads((output/"combined.json").read_text())
    require(r["schema"]==1 and r["status"]==("checking" if finalizing else "passed"),"combined outcome")
    require(r["initial_vm_state"] in ("Absent","Stopped"),"dedicated VM was active during native run")
    require(r["cleanup"]=={"container":"removed","vm":"stopped","errors":[]},"cleanup outcome")
    require(r["container_exit"]=={"Running":False,"ExitCode":0,"OOMKilled":False,"Error":""},"container outcome")
    files = dict(source_manifest()["files"])
    files.update({name:sha(ROOT/name) for name in SETUP})
    require(r["input_files"]==files and r["snapshot_sha256"]==fingerprint(files),"snapshot/current input mismatch")
    required = {"initial-vm-state","base-commit","native-venv","native-install","native-driver","vm-start","docker-info",
                "colima-version","lima-version","image-build","image-info","container-create","container-info","linux-driver",
                "container-exit","linux-export","cleanup-owned","cleanup-inspect","cleanup-remove","cleanup-remaining","vm-stop","final-vm-state"}
    require(required<=set(r["operations"]),"missing validation operation")
    for name,op in r["operations"].items():
        require(op["status"]=="passed" and op["exit_code"]==0 and op["reclaimed_orphans"]==0,"failed/timed-out operation: "+name)
        require(op["log"]==name+".txt" and sha(output/op["log"])==op["log_sha256"],"operation log hash: "+name)
    require((output/"base-commit.txt").read_text().strip()==r["base_commit"],"base ref mismatch")
    require(r["operations"]["native-driver"]["command"][1:3]==["-m","tools.validate"],"wrong native driver")
    require(sha(output/"linux-runtime.json")==r["linux_runtime_sha256"],"runtime hash")
    vm = json.loads((output/"linux-runtime.json").read_text())
    co = vm["container"]
    require(co=={"NetworkMode":"none","Privileged":False,"NanoCpus":4000000000,"Memory":4294967296,
                 "CapDrop":["ALL"],"SecurityOpt":["no-new-privileges"],"Init":True,"user":"validator","mounts":[]},"container isolation")
    im = json.loads((output/"image-info.txt").read_text())[0]
    raw = json.loads((output/"container-info.txt").read_text())[0]
    raw_exit = json.loads((output/"container-exit.txt").read_text())[0]["State"]
    require(all(raw_exit[k]==v for k,v in r["container_exit"].items()),"exit contradicts inspect")
    require(all(im[k]==v for k,v in vm["image"].items()) and raw["Image"]==im["Id"],"image binding")
    require(im["Config"]["Labels"]["tiny-event.snapshot"]==r["snapshot_sha256"],"image snapshot label")
    require(raw["Config"]["Entrypoint"]==["python","-m","tools.validate"]
            and raw["Config"]["Cmd"]==["--output","/evidence/run","--execution-label","colima-linux"],"wrong container driver")
    require(all(raw["HostConfig"][k]==v for k,v in co.items() if k not in ("user","mounts"))
            and raw["Config"]["User"]==co["user"] and raw["Mounts"]==co["mounts"],"runtime contradicts inspect")
    require(vm["NCPU"]==4 and vm["image"]["Os"]=="linux","guest resources/OS")
    states = [json.loads(line) for line in (output/"final-vm-state.txt").read_text().splitlines() if line.strip()]
    require([s["status"] for s in states if s["name"]=="relay"]==["Stopped"],"VM stop contradicts list")
    require(not (output/"cleanup-remaining.txt").read_text().strip(),"owned container survived")
    reports,suites,test_ids = [],[],[]
    for folder,label,system in (("native","native-macos","Darwin"),("linux","colima-linux","Linux")):
        directory = output/folder
        check_validation(directory)
        suite = json.loads((directory/"validation.json").read_text())
        report = json.loads((directory/"benchmark/report.json").read_text())
        env = suite["environment"]
        require(env["execution"]==report["environment"]["execution"]==label and env["system"]==system
                and report["environment"]["platform"].startswith(system+" ") and env["python"]==report["environment"]["python"],"platform/label metadata")
        require(suite["module_origins"]=={"relay":"relay/__init__.py","tests":"tests/__init__.py"},"wrong implementation import")
        require(all(r["input_files"][name]==digest for name,digest in suite["source"]["files"].items()),"source/snapshot binding")
        test_ids.append(json.loads((directory/"tests/tests.json").read_text())["expected"])
        suites.append(suite)
        reports.append(report)
    require(test_ids[0]==test_ids[1] and suites[0]["source"]==suites[1]["source"],"different formal tests or implementation")
    require(reports[0]["parameters"]==reports[1]["parameters"],"different workload parameters")
    def schedule(report):
        return {(t["scenario"],t["blob_bytes"],t["repeat"]):[(row["id"],row["scheduled_s"],row["digest"],row["canonical_bytes"]) for row in t["records"]]
                for t in report["trials"]}
    require(schedule(reports[0])==schedule(reports[1]),"different scheduled arrivals or payloads")
    arch = [ALIASES.get(s["environment"]["machine"]) for s in suites]+[ALIASES.get(vm["Architecture"]),ALIASES.get(vm["image"]["Architecture"])]
    require(arch[0] is not None and len(set(arch))==1,"emulated or mismatched architecture")
    if not finalizing:
        require((output/"report.html").read_text()==render_overview(r,*reports),"overview HTML mismatch")
    return reports


def render_overview(receipt,native,linux):
    sections = []
    for title,folder,report in (("Native macOS (host)","native",native),("Linux (Colima VM + container)","linux",linux)):
        rows = []
        for group in report["aggregate"]:
            s = group["median_of_trial_summaries"]
            values = [group["scenario"],group["blob_bytes"],f'{s["accept_p95_ms"]:.2f}',f'{s["effect_p95_ms"]:.2f}',
                      f'{s["unique_effects_per_s"]:.2f}',f'{s["peak_relay_rss_bytes"]/1048576:.2f}',f'{s["peak_database_family_bytes"]/1048576:.3f}']
            rows.append("<tr>"+"".join("<td>"+html.escape(str(v))+"</td>" for v in values)+"</tr>")
        sections.append("<section><h2>"+title+"</h2><p>"+html.escape(report["environment"]["platform"])+
                        f'</p><p><a href="{folder}/benchmark/report.html">Full report</a> · <a href="{folder}/benchmark/report.json">Raw JSON</a></p>'+
                        "<table><tr><th>Scenario</th><th>Blob bytes</th><th>Accept p95 ms</th><th>Commit p95 ms</th><th>Unique effects/s</th><th>Relay sampled RSS MiB</th><th>Apparent DB+WAL+SHM MiB</th></tr>"+"".join(rows)+"</table></section>")
    return ('<!doctype html><html lang="en"><meta charset="utf-8"><title>tiny-event-relay local validation</title>'
            '<style>body{font:16px system-ui;max-width:1100px;margin:40px auto;padding:0 20px;color:#183044}table{border-collapse:collapse;width:100%}th,td{padding:9px;border:1px solid #ccd6df;text-align:left}th{background:#edf3f7}section{margin:35px 0}code{overflow-wrap:anywhere}</style>'
            '<h1>Same-source local validation</h1><p>Each environment runs the same formal tests, mutations and 18 fresh-database trials. Tables show medians of three trial summaries, not pooled percentiles.</p>'
            '<p>Native and VM results remain separate. Guest CPU/storage/filesystem and synchronization behavior differ from the host; these numbers do not establish a native Linux speedup or a cross-OS memory advantage. Linux RSS covers only the guest relay process, not host VM overhead. Disk values are apparent file lengths, not VM-disk allocation. Initial startup peaks and short sampling peaks may be missed.</p>'
            '<p>Linux VM: 4 vCPU, 6 GiB configured RAM; container: 4 CPU quota, 4 GiB memory, non-root, no network or host mounts. Native runs while the owned VM is stopped; unrelated host load is uncontrolled.</p>'
            '<p>Snapshot SHA-256: <code>'+receipt["snapshot_sha256"]+'</code></p>'+"".join(sections)+"</html>\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory",type=Path)
    args = parser.parse_args()
    n,l = check_local(args.directory)
    print(f"Verified both formal suites and {len(n['trials'])+len(l['trials'])} trials; source/test/schedule identity and cleanup passed.")


if __name__=="__main__":
    main()
