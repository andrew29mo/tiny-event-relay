import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source_manifest():
    paths = [*ROOT.glob("relay/*.py"),*ROOT.glob("tools/*.py"),*ROOT.glob("tests/*.py"),
             ROOT/"pyproject.toml",ROOT/"requirements-dev.txt"]
    files = {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
    digest = hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()
    return {"sha256":digest,"files":files}


def sanitize(text):
    import sys
    import tempfile
    return text.replace(str(ROOT),"<repo>").replace(tempfile.gettempdir(),"<tmp>").replace(str(Path.home()),"<home>").replace(str(Path(sys.base_prefix)),"<python>")
