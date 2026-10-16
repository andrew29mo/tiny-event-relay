"""Regressions for observed review gaps; no benchmark fixture stands in for the relay."""
import json
import socket
import sqlite3
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from relay.httpio import json_request,request
from tests.support import Stack,wait_for
from tests.test_reports import fixture
from tools.benchmark import Sampler
from tools.check_report import check


class LiveReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.stack = Stack(self.temp.name)
        self.addCleanup(self.stack.close)

    def database(self):
        return sqlite3.connect(Path(self.temp.name)/"queue/queue.sqlite",isolation_level=None)

    def test_storage_failure_through_real_http_never_acknowledges(self):
        s = self.stack.start()
        with self.database() as db:
            db.execute("CREATE TRIGGER deny_insert BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT,'test write failure'); END")
        self.assertEqual(s.submit("blocked")[0],503)
        self.assertEqual(json_request(s.url+"/v1/events/blocked")[0],404)
        self.assertEqual(s.effects()["effects"],[])
        with self.database() as db:
            db.execute("DROP TRIGGER deny_insert")
        self.assertEqual(s.submit("blocked")[0],202)
        s.delivered("blocked")

    def test_requeue_storage_failure_is_a_structured_503(self):
        s = self.stack.start()
        s.control("permanent")
        self.assertEqual(s.submit("dead")[0],202)
        wait_for(lambda: s.event("dead")["state"]=="dead_letter")
        with self.database() as db:
            db.execute("""CREATE TRIGGER deny_requeue BEFORE UPDATE ON events
                        WHEN OLD.state='dead_letter' AND NEW.state='pending'
                        BEGIN SELECT RAISE(ABORT,'test requeue failure'); END""")
        status,body = json_request(s.url+"/v1/requeue/dead","POST",{})
        self.assertEqual(status,503)
        self.assertIn("storage unavailable",body["error"])
        self.assertEqual(s.event("dead")["state"],"dead_letter")

    def test_acceptance_waits_for_actual_database_transaction(self):
        s = self.stack.start()
        db = self.database()
        self.addCleanup(db.close)
        db.execute("BEGIN IMMEDIATE")
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(s.submit,"commit-boundary")
            time.sleep(.12)
            premature = future.done()
            self.assertEqual(s.effects()["effects"],[])
            db.execute("COMMIT")
            self.assertFalse(premature,"HTTP acknowledgment escaped a blocked transaction")
            self.assertEqual(future.result(timeout=4)[0],202)
        # An independent SQLite reader can see the row after the HTTP acknowledgment.
        self.assertEqual(db.execute("SELECT count(*) FROM events WHERE id='commit-boundary'").fetchone()[0],1)
        s.delivered("commit-boundary")

    def test_concurrent_duplicate_and_capacity_admission(self):
        self.stack.extra = ["--max-events","4"]
        s = self.stack.start()
        s.sink.stop()
        # Queue the repeated ID first, then challenge serialization with separate sockets.
        self.assertEqual(s.submit("same")[0],202)
        names = ["same"]*6+[f"unique-{i}" for i in range(8)]
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda name: s.submit(name)[0],names))
        self.assertEqual(results[:6],[200]*6)
        self.assertEqual(results[6:].count(202),3)
        self.assertEqual(results[6:].count(507),5)
        stats = json_request(s.url+"/v1/stats")[1]
        self.assertEqual(sum(stats["states"].values()),4)
        self.assertEqual(s.submit("same",{"different":True})[0],409)

    def test_unresolved_event_is_not_pruned_by_receipt_ttl(self):
        self.stack.extra = ["--receipt-ttl","0.05","--max-events","1"]
        s = self.stack.start()
        s.sink.stop()
        self.assertEqual(s.submit("pending")[0],202)
        time.sleep(.1)
        self.assertEqual(s.submit("pending")[0],200)
        self.assertEqual(s.submit("pending",42)[0],409)
        self.assertEqual(s.submit("new")[0],507)
        s.relay.stop(kill=True)
        s.start_relay()
        self.assertEqual(s.submit("pending")[0],200)
        s.start_sink()
        s.delivered("pending")
        self.assertEqual(len(s.effects()["effects"]),1)

    def test_browser_origin_and_foreign_host_are_rejected(self):
        s = self.stack.start()
        for headers,expected in (({"Origin":"https://untrusted.invalid"},403),
                                 ({"Host":"untrusted.invalid"},400),
                                 ({"Sec-Fetch-Site":"cross-site"},403)):
            body = json.dumps({"event_id":"untrusted","payload":1}).encode()
            self.assertEqual(request(s.url+"/v1/events","POST",body,headers)[0],expected)
            sink_headers = {**headers,"Idempotency-Key":"untrusted"}
            self.assertEqual(request(s.sink_url+"/events","POST",b"1",sink_headers)[0],expected)
        self.assertEqual(json_request(s.url+"/v1/stats")[1]["states"],{})
        self.assertEqual(s.effects()["effects"],[])
        self.assertEqual(s.submit("trusted")[0],202)
        s.delivered("trusted")


class MeasurementReviewTests(unittest.TestCase):
    def test_partial_sampler_failure_cannot_pass(self):
        class StackStub:
            relay = None
            directory = Path("unused")
        sampler = Sampler(StackStub())
        def broken():
            sampler.samples.append({"elapsed_s":0})
            raise PermissionError("injected sample failure")
        with patch.object(sampler,"run",side_effect=broken):
            with self.assertRaisesRegex(AssertionError,"sampl"):
                with sampler:
                    time.sleep(.02)

    def test_empty_passed_report_is_rejected(self):
        report = fixture()
        report["parameters"]["repeats"] = 0
        report["trials"] = []
        report["aggregate"] = []
        with self.assertRaises(ValueError):
            check(report)

    def test_truncated_resource_samples_are_rejected(self):
        report = fixture()
        report["trials"][0]["samples"] = report["trials"][0]["samples"][:3]
        with self.assertRaisesRegex(ValueError,"sampling"):
            check(report)

    def test_missing_restart_rss_lifetime_is_rejected(self):
        report = fixture()
        trial = next(t for t in report["trials"] if t["scenario"]=="restart")
        for sample in trial["samples"]:
            if sample["pid"]==2:
                sample["relay_rss_bytes"] = None
        with self.assertRaisesRegex(ValueError,"RSS"):
            check(report)

    def test_wall_clock_change_does_not_change_monotonic_latency(self):
        report = fixture()
        for trial in report["trials"]:
            trial["wall_clock_drift_s"] = -3600
            for effect in trial["receiver_receipt"]["effects"]:
                effect["committed"] -= 3600
        check(report)
