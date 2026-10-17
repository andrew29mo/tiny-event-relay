"""Sequential same-snapshot native macOS and dedicated Colima Linux validation."""
import argparse
from datetime import datetime,timezone
import fcntl
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import uuid

from .evidence import ROOT,source_manifest
from .install_colima import install
from .platform_io import sha,save,fingerprint
from .validation_process import execute,cancellation_signals,cleanup_signals

SETUP = ("containers/validation.Dockerfile","tools/colima-lock.json","tools/validate-local","LICENSE","THIRD_PARTY_NOTICES.md")


def inventory():
    files = dict(source_manifest()["files"])
    files.update({name:sha(ROOT/name) for name in SETUP})
    tracked = set(subprocess.check_output(["git","ls-files","-z"],cwd=ROOT,timeout=20).decode().split("\0"))
    if not set(files)<=tracked:
        raise RuntimeError("Stage validation inputs before making an immutable snapshot")
    return files


def check_snapshot(root,files):
    root = Path(root).resolve()
    for name,digest in files.items():
        p = root/name
        if p.is_symlink() or not p.is_file() or not p.resolve().is_relative_to(root) or sha(p)!=digest:
            raise RuntimeError("Snapshot input changed or is not an ordinary input file: "+name)


def copy_snapshot(root,target,files):
    check_snapshot(root,files)
    for name in files:
        dest = target/name
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(root/name,dest)
    check_snapshot(target,files)


class Commands:
    def __init__(self,output,receipt):
        self.output,self.receipt,self.env = output,receipt,None

    def call(self,name,command,timeout=120,check=True,cwd=ROOT):
        try:
            result = execute(command,self.output/(name+".txt"),timeout=timeout,cwd=cwd,env=self.env,
                             reap_orphans=name=="native-driver")
        except BaseException as exc:
            self.receipt["operations"][name] = {"status":"interrupted","error_type":type(exc).__name__,"log":name+".txt"}
            save(self.output/"combined.json",self.receipt)
            raise
        self.receipt["operations"][name] = result
        save(self.output/"combined.json",self.receipt)
        if check and (result["status"]!="passed" or result["exit_code"]!=0):
            raise RuntimeError("Command failed or timed out: "+name)
        return result

    def capture(self,name,command,**kwargs):
        self.call(name,command,**kwargs)
        return (self.output/(name+".txt")).read_text().strip()


def profile_state(c,colima,label):
    items = [json.loads(line) for line in c.capture(label,[colima,"list","--json"]).splitlines() if line.strip()]
    items = [p for p in items if p["name"]=="relay"]
    if len(items)>1:
        raise RuntimeError("Ambiguous dedicated VM profile")
    return items[0]["status"] if items else "Absent"


def remove_owned_container(c,docker,ident,output,exported):
    state = json.loads(c.capture("cleanup-inspect",[docker,"inspect",ident]))[0]["State"]
    if state["Running"]:
        c.call("cleanup-kill",[docker,"kill",ident])
    if not exported:
        recovery = c.call("cleanup-export",[docker,"cp",ident+":/evidence",str(output/"linux-failed")],check=False)
        if recovery["status"]!="passed" or recovery["exit_code"]!=0:
            raise RuntimeError("Evidence export failed; stopped container retained for recovery")
    c.call("cleanup-remove",[docker,"rm",ident])


def run(output,retain=None):
    if platform.system()!="Darwin" or sys.version_info[:2]!=(3,12):
        raise RuntimeError("Use macOS with the project Python 3.12 environment")
    output = Path(output).resolve()
    if not output.is_relative_to(ROOT/"results/local"):
        raise ValueError("Raw output must be inside ignored results/local")
    if retain is not None:
        retain = Path(retain).resolve()
        if not retain.is_relative_to(ROOT/"reviews") or retain.exists():
            raise ValueError("Retained evidence must be a fresh directory inside reviews/")
    output.mkdir(parents=True,exist_ok=False)
    r = {"schema":1,"status":"running","created_utc":datetime.now(timezone.utc).isoformat(),"operations":{},
         "scope":"Native macOS and Colima Linux VM are separate measurements; no cross-OS speedup or RSS ratio."}
    save(output/"combined.json",r)
    c = Commands(output,r)
    token = uuid.uuid4().hex
    colima = docker = None
    attempted = exported = False
    with (ROOT/"results/local/validation.lock").open("a") as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            r.update(status="failed",error_type="ProjectValidationAlreadyRunning")
            save(output/"combined.json",r)
            raise RuntimeError("Another validation owns this project's VM") from None
        try:
            try:
                binaries,c.env = install()
                for name in ("PYTHONPATH","PYTHONHOME","PIP_TARGET","PIP_PREFIX","PIP_USER","LIMA_HOME","COLIMA_PROFILE"):
                    c.env.pop(name,None)
                c.env["PYTHONNOUSERSITE"] = "1"
                colima,docker = str(binaries/"colima"),str(binaries/"docker")
                r["initial_vm_state"] = profile_state(c,colima,"initial-vm-state")
                if r["initial_vm_state"] not in ("Stopped","Absent"):
                    raise RuntimeError("Dedicated relay VM is already running; it was not started or stopped by this run")
                files = inventory()
                r.update(input_files=files,snapshot_sha256=fingerprint(files),base_commit=c.capture("base-commit",["git","rev-parse","HEAD"]))
                workspace = output/"context/workspace"
                copy_snapshot(ROOT,workspace,files)
                python = str(output/"native-env/bin/python")
                c.call("native-venv",[sys.executable,"-m","venv",str(output/"native-env")])
                c.call("native-install",[python,"-m","pip","install","-r","requirements-dev.txt"],cwd=workspace,timeout=300)
                print("Running native macOS validation; dedicated VM remains stopped.",flush=True)
                c.call("native-driver",[python,"-m","tools.validate","--output",str(output/"native"),"--execution-label","native-macos"],cwd=workspace,timeout=900)
                check_snapshot(workspace,files)
                attempted = True
                print("Starting dedicated Colima relay VM.",flush=True)
                c.call("vm-start",[colima,"start","relay","--cpu","4","--memory","6","--disk","30","--vm-type","vz","--runtime","docker",
                                   "--mount","none","--activate=false","--ssh-config=false","--ssh-agent=false","--vz-rosetta=false","--binfmt=false"],timeout=900)
                info = json.loads(c.capture("docker-info",[docker,"info","--format","{{json .}} "]))
                runtime = {k:info[k] for k in ("ServerVersion","KernelVersion","Architecture","OperatingSystem","NCPU","MemTotal")}
                expected = ("aarch64","arm64") if platform.machine()=="arm64" else ("x86_64","amd64")
                if runtime["Architecture"] not in expected:
                    raise RuntimeError("Unexpected/emulated guest architecture")
                runtime["colima_version"] = c.capture("colima-version",[colima,"version"])
                runtime["lima_version"] = c.capture("lima-version",[str(binaries/"limactl"),"--version"])
                shutil.copy2(workspace/"containers/validation.Dockerfile",output/"context/Dockerfile")
                image = "tiny-event-validation:"+token
                c.call("image-build",[docker,"build","--load","--label","tiny-event.snapshot="+r["snapshot_sha256"],"-t",image,str(output/"context")],timeout=900)
                im = json.loads(c.capture("image-info",[docker,"image","inspect",image]))[0]
                runtime["image"] = {k:im[k] for k in ("Id","Architecture","Os")}
                name = "tiny-event-validation-"+token
                c.call("container-create",[docker,"create","--name",name,"--label","tiny-event.validation.run="+token,"--init","--network","none",
                                           "--cap-drop","ALL","--security-opt","no-new-privileges","--cpus","4","--memory","4g",im["Id"],
                                           "--output","/evidence/run","--execution-label","colima-linux"])
                ci = json.loads(c.capture("container-info",[docker,"inspect",name]))[0]
                runtime["container"] = {k:ci["HostConfig"][k] for k in ("NetworkMode","Privileged","NanoCpus","Memory","CapDrop","SecurityOpt","Init")}
                runtime["container"].update(user=ci["Config"]["User"],mounts=ci["Mounts"])
                save(output/"linux-runtime.json",runtime)
                r["linux_runtime_sha256"] = sha(output/"linux-runtime.json")
                print("Running Linux validation and separate guest measurements.",flush=True)
                attached = c.call("linux-driver",[docker,"start","--attach",name],timeout=900,check=False)
                state = json.loads(c.capture("container-exit",[docker,"inspect",name]))[0]["State"]
                r["container_exit"] = {k:state[k] for k in ("Running","ExitCode","OOMKilled","Error")}
                c.call("linux-export",[docker,"cp",name+":/evidence/run",str(output/"linux")])
                exported = True
                if attached["status"]!="passed" or state["ExitCode"]!=0 or state["Running"] or state["OOMKilled"] or state["Error"]:
                    raise RuntimeError("Linux container/attach failed or was OOM-killed")
                check_snapshot(workspace,files)
                if inventory()!=files:
                    raise RuntimeError("Working input changed during validation")
            finally:
                with cleanup_signals():
                    cleanup = {"container":"not-created","vm":"not-started","errors":[]}
                    if docker and attempted:
                        try:
                            ids = c.capture("cleanup-owned",[docker,"ps","-aq","--filter","label=tiny-event.validation.run="+token]).split()
                            for ident in ids:
                                remove_owned_container(c,docker,ident,output,exported)
                            if c.capture("cleanup-remaining",[docker,"ps","-aq","--filter","label=tiny-event.validation.run="+token]):
                                raise RuntimeError("Owned container survived cleanup")
                            cleanup["container"] = "removed"
                        except BaseException as exc:
                            cleanup["errors"].append("container: "+type(exc).__name__)
                    if colima and attempted:
                        try:
                            c.call("vm-stop",[colima,"stop","relay"],timeout=180)
                            if profile_state(c,colima,"final-vm-state")!="Stopped":
                                raise RuntimeError("Dedicated VM did not stop")
                            cleanup["vm"] = "stopped"
                        except BaseException as exc:
                            cleanup["errors"].append("vm: "+type(exc).__name__)
                    r["cleanup"] = cleanup
                    save(output/"combined.json",r)
            if r["cleanup"]["errors"]:
                raise RuntimeError("Cleanup failed; see retained recovery information")
            r["status"] = "checking"
            save(output/"combined.json",r)
            from .check_local import check_local,render_overview
            native,linux = check_local(output,finalizing=True)
            (output/"report.html").write_text(render_overview(r,native,linux))
            r["status"] = "passed"
            save(output/"combined.json",r)
            if retain is not None:
                from .retain_validation import retain_evidence
                retain_evidence(output,retain)
        except BaseException as exc:
            r.update(status="failed",error_type=type(exc).__name__)
            save(output/"combined.json",r)
            raise
    print("Both environments verified; owned container removed and VM stopped.",flush=True)
    return r


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,default=ROOT/"results/local"/("dual-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")))
    parser.add_argument("--retain",type=Path,help="export privacy-normalized evidence into a fresh reviews/ directory")
    args = parser.parse_args()
    with cancellation_signals():
        run(args.output,args.retain)


if __name__=="__main__":
    main()
