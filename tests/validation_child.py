"""Cooperative process fixtures for actual validator timeout/cleanup regression tests."""
import json
import signal
import subprocess
import sys
import time
from pathlib import Path

from tools.validate import run_step


def interrupted(*_):
    raise KeyboardInterrupt


def main():
    mode = sys.argv[1]
    if mode=="fail":
        raise SystemExit(7)
    if mode=="orphan":
        subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"],start_new_session=True,
                         stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        time.sleep(.05)
        return
    if mode=="sleep":
        if len(sys.argv)>2:
            import os
            Path(sys.argv[2]).write_text(str(os.getpid()))
        time.sleep(60)
        return
    if mode=="runner":
        signal.signal(signal.SIGTERM,interrupted)
        directory = Path(sys.argv[2])
        result = run_step(["tests.validation_child","sleep",str(directory/"child.pid")],directory/"child.log",30)
        (directory/"result.json").write_text(json.dumps(result))
        raise SystemExit(0 if result["passed"] else 1)
    raise ValueError("unknown fixture")


if __name__=="__main__":
    main()
