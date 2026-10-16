import json
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import psutil

from tests.support import ROOT,wait_for
from tools.validate import run_step


class ValidationTests(unittest.TestCase):
    def test_failed_command_cannot_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run_step(["tests.validation_child","fail"],Path(directory)/"log",3)
            self.assertFalse(result["passed"])
            self.assertEqual(result["exit_code"],7)
            self.assertTrue(result["cleanup_complete"])

    def test_timeout_cannot_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run_step(["tests.validation_child","sleep"],Path(directory)/"log",.15)
            self.assertFalse(result["passed"])
            self.assertTrue(result["timed_out"])
            self.assertTrue(result["cleanup_complete"])

    def test_successful_parent_leaving_detached_child_is_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run_step(["tests.validation_child","orphan"],Path(directory)/"log",3)
            self.assertFalse(result["passed"])
            self.assertEqual(result["exit_code"],0)
            self.assertGreaterEqual(result["cleanup_required"],1)
            self.assertTrue(result["cleanup_complete"])

    def test_interrupt_cleans_owned_process_and_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = subprocess.Popen([sys.executable,"-m","tests.validation_child","runner",directory],cwd=ROOT,
                                      stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            pid = None
            try:
                wait_for(lambda: (root/"child.pid").exists())
                pid = int((root/"child.pid").read_text())
                runner.send_signal(signal.SIGTERM)
                self.assertNotEqual(runner.wait(timeout=8),0)
                result = json.loads((root/"result.json").read_text())
                self.assertTrue(result["interrupted"])
                self.assertTrue(result["cleanup_complete"])
                self.assertFalse(result["passed"])
                self.assertFalse(psutil.pid_exists(pid))
            finally:
                if runner.poll() is None:
                    runner.kill()
                runner.wait(timeout=3)
                if pid and psutil.pid_exists(pid):
                    psutil.Process(pid).kill()
