"""Small evidence I/O primitives shared by the host controller and its checker."""
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path,value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix+".tmp")
    temporary.write_text(json.dumps(value,indent=2)+"\n")
    temporary.replace(path)


def fingerprint(files):
    return hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()
