"""Portable checks for the real host controller's snapshot, failure and recovery paths."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

from tools.platform_io import sha
from tools.validate_local import copy_snapshot,check_snapshot,remove_owned_container,profile_state
from tools.validation_process import execute


class SnapshotTests(unittest.TestCase):
    def test_snapshot_copies_exact_input_and_detects_later_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/"source"
            root.mkdir()
            (root/"a.py").write_text("x=1\n")
            files = {"a.py":sha(root/"a.py")}
            target = Path(directory)/"snapshot"
            copy_snapshot(root,target,files)
            self.assertEqual(sha(target/"a.py"),files["a.py"])
            (target/"a.py").write_text("x=2\n")
            with self.assertRaisesRegex(RuntimeError,"Snapshot"):
                check_snapshot(target,files)

    def test_snapshot_refuses_symlink_and_parent_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/"source"
            root.mkdir()
            external = Path(directory)/"outside.py"
            external.write_text("x=1\n")
            (root/"link.py").symlink_to(external)
            for name in ("link.py","../outside.py"):
                with self.assertRaisesRegex(RuntimeError,"Snapshot"):
                    check_snapshot(root,{name:sha(external)})


class OuterProcessTests(unittest.TestCase):
    def test_nonzero_command_is_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            r = execute([sys.executable,"-c","raise SystemExit(7)"],Path(directory)/"log",timeout=3)
            self.assertEqual(r["status"],"failed")
            self.assertEqual(r["exit_code"],7)

    def test_timeout_cannot_be_success_even_when_sigterm_exits_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            r = execute([sys.executable,"-c","import signal,time; signal.signal(signal.SIGTERM,lambda *_:exit(0)); print('ready',flush=True); time.sleep(60)"],
                        Path(directory)/"log",timeout=.5)
            self.assertEqual(r["status"],"timeout")
            self.assertEqual(r["exit_code"],0)

    def test_detached_child_after_successful_parent_is_reclaimed_and_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            r = execute([sys.executable,"-m","tests.validation_child","orphan"],Path(directory)/"log",timeout=3)
            self.assertEqual(r["exit_code"],0)
            self.assertEqual(r["status"],"failed")
            self.assertGreaterEqual(r["reclaimed_orphans"],1)


class ContainerRecoveryTests(unittest.TestCase):
    def test_failed_export_retains_stopped_container(self):
        class Commands:
            removed = False
            def capture(self,*args):
                return json.dumps([{"State":{"Running":False}}])
            def call(self,name,*args,**kwargs):
                if name=="cleanup-remove":self.removed=True
                return {"status":"failed","exit_code":1}
        c = Commands()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError,"retained"):
                remove_owned_container(c,"docker","owned",Path(directory),False)
        self.assertFalse(c.removed)

    def test_successful_export_precedes_container_removal(self):
        class Commands:
            def __init__(self):self.order=[]
            def capture(self,*args):
                return json.dumps([{"State":{"Running":True}}])
            def call(self,name,*args,**kwargs):
                self.order.append(name)
                return {"status":"passed","exit_code":0}
        c = Commands()
        with tempfile.TemporaryDirectory() as directory:
            remove_owned_container(c,"docker","owned",Path(directory),False)
        self.assertEqual(c.order,["cleanup-kill","cleanup-export","cleanup-remove"])

    def test_profile_inventory_ignores_unrelated_profiles(self):
        class Commands:
            def capture(self,*args):
                return json.dumps({"name":"unrelated","status":"Running"})+"\n"+json.dumps({"name":"relay","status":"Stopped"})
        self.assertEqual(profile_state(Commands(),"colima","probe"),"Stopped")
