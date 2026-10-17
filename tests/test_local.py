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


class ControllerFailureTests(unittest.TestCase):
    """Mock infrastructure outcomes only; exercise the actual controller/finally logic."""
    def exercise(self, *, failed=None, outcome=None, initial="Stopped", missing_evidence=False):
        from unittest.mock import patch
        from contextlib import redirect_stdout
        import io
        from tools import validate_local as controller
        from tools.platform_io import save
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root/"results/local").mkdir(parents=True)
            output = root/"results/local/run"
            calls = []
            state = {"Running":False,"ExitCode":0,"OOMKilled":False,"Error":""}
            state.update(outcome or {})

            class Commands:
                def __init__(self, output, receipt):
                    self.output,self.receipt,self.env = output,receipt,None
                def call(self, name, command, check=True, **kwargs):
                    calls.append(name)
                    status = failed[1] if failed and name==failed[0] else "passed"
                    result = {"status":status,"exit_code":0 if status in ("passed","timeout") else 7}
                    self.receipt["operations"][name] = result
                    save(self.output/"combined.json",self.receipt)
                    if check and status!="passed":
                        raise RuntimeError("injected infrastructure outcome: "+name)
                    return result
                def capture(self, name, command, **kwargs):
                    self.call(name,command,**kwargs)
                    values = {
                        "initial-vm-state":json.dumps({"name":"relay","status":initial}),
                        "base-commit":"a"*40,
                        "docker-info":json.dumps(dict(ServerVersion="test",KernelVersion="test",Architecture="arm64",
                                                       OperatingSystem="Linux",NCPU=4,MemTotal=6*1024**3)),
                        "image-info":json.dumps([dict(Id="sha256:test",Architecture="arm64",Os="linux")]),
                        "container-info":json.dumps([dict(HostConfig={k:None for k in
                              ("NetworkMode","Privileged","NanoCpus","Memory","CapDrop","SecurityOpt","Init")},
                              Config={"User":"validator"},Mounts=[])]),
                        "container-exit":json.dumps([{"State":state}]),
                        "cleanup-owned":"owned" if "container-create" in calls else "",
                        "cleanup-inspect":json.dumps([{"State":{"Running":False}}]),
                        "cleanup-remaining":"",
                        "final-vm-state":json.dumps({"name":"relay","status":"Stopped"}),
                    }
                    return values.get(name,"test")

            # Copy a real ordinary setup file so image-build preparation executes.
            def snapshot(source,target,files):
                (target/"containers").mkdir(parents=True)
                (target/"containers/validation.Dockerfile").write_text("FROM scratch\n")

            with patch.object(controller,"ROOT",root), patch.object(controller,"Commands",Commands), \
                 patch.object(controller,"install",return_value=(root/"bin",{})), \
                 patch.object(controller,"inventory",return_value={}), \
                 patch.object(controller,"copy_snapshot",side_effect=snapshot), \
                 patch.object(controller,"check_snapshot"), \
                 patch.object(controller.platform,"system",return_value="Darwin"), \
                 patch.object(controller.platform,"machine",return_value="arm64"), \
                 patch.object(controller.sys,"version_info",(3,12)), \
                 patch("tools.retain_validation.retain_evidence") as retain:
                with redirect_stdout(io.StringIO()), self.assertRaises((RuntimeError,ValueError,FileNotFoundError,KeyError)):
                    controller.run(output,root/"reviews/retained")
                retain.assert_not_called()
            receipt = json.loads((output/"combined.json").read_text())
            self.assertEqual(receipt["status"],"failed")
            self.assertFalse((root/"reviews/retained").exists())
            if missing_evidence:
                self.assertEqual(receipt["cleanup"],{"container":"removed","vm":"stopped","errors":[]})
            return calls,receipt

    def test_native_failure_never_starts_vm(self):
        calls,_ = self.exercise(failed=("native-driver","failed"))
        self.assertNotIn("vm-start",calls)

    def test_native_timeout_with_zero_exit_never_starts_vm(self):
        calls,_ = self.exercise(failed=("native-driver","timeout"))
        self.assertNotIn("vm-start",calls)

    def test_linux_attach_timeout_with_zero_container_exit_still_fails(self):
        calls,r = self.exercise(failed=("linux-driver","timeout"))
        self.assertIn("cleanup-remove",calls)
        self.assertEqual(r["cleanup"]["vm"],"stopped")

    def test_nonzero_and_oom_container_outcomes_fail(self):
        for outcome in ({"ExitCode":7},{"OOMKilled":True},{"Running":True},{"Error":"runtime error"}):
            with self.subTest(outcome=outcome):
                calls,_ = self.exercise(outcome=outcome)
                self.assertIn("vm-stop",calls)

    def test_cleanup_failure_cannot_be_success(self):
        for operation in ("cleanup-remove","vm-stop"):
            with self.subTest(operation=operation):
                _,r = self.exercise(failed=(operation,"failed"))
                self.assertTrue(r["cleanup"]["errors"])

    def test_already_running_vm_is_not_stopped(self):
        calls,_ = self.exercise(initial="Running")
        self.assertNotIn("vm-start",calls)
        self.assertNotIn("vm-stop",calls)

    def test_zero_exit_without_complete_receipts_cannot_pass(self):
        self.exercise(missing_evidence=True)


class RetentionFailureTests(unittest.TestCase):
    def test_failed_export_check_removes_partial_copy(self):
        from unittest.mock import patch
        from tools.retain_validation import retain_evidence
        from tools.platform_io import save
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source,target = root/"source",root/"retained"
            source.mkdir()
            save(source/"combined.json",{"operations":{}})
            save(source/"linux-runtime.json",{})
            for name in ("native","linux"):
                (source/name/"tests").mkdir(parents=True)
                (source/name/"tests/tests.txt").write_text("unchanged\n")
                save(source/name/"tests/tests.json",{})
                save(source/name/"validation.json",{"steps":[]})
            with patch("tools.check_local.check_local",side_effect=[None,ValueError("injected export check")]):
                with self.assertRaisesRegex(ValueError,"injected export check"):
                    retain_evidence(source,target)
            self.assertFalse(target.exists())
            self.assertEqual(list(root.glob("retained.partial-*")),[])
            self.assertEqual((source/"native/tests/tests.txt").read_text(),"unchanged\n")

    def test_copy_error_also_removes_partial_copy(self):
        from unittest.mock import patch
        from tools.retain_validation import retain_evidence
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source,target = root/"source",root/"retained"
            source.mkdir()
            (source/"bad.txt").write_bytes(b"\xff")
            with patch("tools.check_local.check_local",return_value=None):
                with self.assertRaises(UnicodeDecodeError):
                    retain_evidence(source,target)
            self.assertFalse(target.exists())
            self.assertEqual(list(root.glob("retained.partial-*")),[])
