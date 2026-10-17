"""Export only validated evidence; normalize private paths and rebind changed log hashes."""
import json
from pathlib import Path
import re
import shutil
import tempfile
import uuid

from .evidence import ROOT
from .platform_io import sha,save


def retain_evidence(source,target):
    from .check_local import check_local
    source,target = Path(source),Path(target)
    check_local(source)
    if target.exists():
        raise ValueError("Retained evidence already exists")
    temporary = target.with_name(target.name+".partial-"+uuid.uuid4().hex[:8])
    temporary.mkdir(parents=True)
    try:
        originals = {}
        selected = [p for p in source.iterdir() if p.is_file() and p.suffix in (".json",".txt",".html")]
        for folder in ("native","linux"):
            selected.extend(p for p in (source/folder).rglob("*") if p.is_file() and p.suffix in (".json",".txt",".html"))
        for p in selected:
            name = p.relative_to(source)
            originals[str(name)] = sha(p)
            out = temporary/name
            out.parent.mkdir(parents=True,exist_ok=True)
            text = p.read_text()
            for value,label in ((str(source),"<evidence>"),(str(ROOT),"<repo>"),(tempfile.gettempdir(),"<tmp>"),(str(Path.home()),"<home>")):
                text = text.replace(value,label)
            text = re.sub(r"(https?://)[^\s/@]+:[^\s/@]+@",r"\1<credentials>@",text)
            out.write_text(text)
        for folder in ("native","linux"):
            d = temporary/folder
            tests = json.loads((d/"tests/tests.json").read_text())
            tests["log_sha256"] = sha(d/"tests/tests.txt")
            save(d/"tests/tests.json",tests)
            suite = json.loads((d/"validation.json").read_text())
            for i,step in enumerate(suite["steps"],1):
                step["log_sha256"] = sha(d/f"step-{i}.txt")
            save(d/"validation.json",suite)
        combined = json.loads((temporary/"combined.json").read_text())
        combined["status"] = "checking"
        for name,op in combined["operations"].items():
            op["log_sha256"] = sha(temporary/op["log"])
        combined["linux_runtime_sha256"] = sha(temporary/"linux-runtime.json")
        combined["redaction"] = {"paths":"repo/home/temp/evidence placeholders","original_sha256_file":"original-digests.json"}
        save(temporary/"original-digests.json",originals)
        save(temporary/"combined.json",combined)
        check_local(temporary,finalizing=True)
        combined["status"] = "passed"
        save(temporary/"combined.json",combined)
        check_local(temporary)
        temporary.rename(target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
