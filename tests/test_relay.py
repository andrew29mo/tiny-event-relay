import hashlib
import json
import sqlite3
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from relay.httpio import json_request, request
from relay.service import canonical
from relay.store import Store, CapacityError
from tests.support import Stack,wait_for,ROOT


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.stack = Stack(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.stack.close)

    def start(self,extra=()):
        self.stack.extra = list(extra)
        self.stack.start()
        return self.stack

    def test_canonical_delivery_and_duplicate_conflict(self):
        s = self.start()
        payload = {"b":[2,3],"a":"test"}
        self.assertEqual(s.submit("one",payload)[0],202)
        s.delivered("one")
        self.assertEqual(s.submit("one",{"a":"test","b":[2,3]})[0],200)
        self.assertEqual(s.submit("one",{"b":4})[0],409)
        effects = s.effects()
        self.assertEqual(effects["attempts"],{"one":1})
        self.assertEqual(effects["effects"][0]["digest"],hashlib.sha256(canonical(payload)).hexdigest())
        self.assertGreaterEqual(effects["effects"][0]["committed"],effects["effects"][0]["transaction_recorded"])
        # Independent contents oracle: do not let a shared canonical() bug hide field loss.
        with sqlite3.connect(Path(self.temp.name)/"sink.sqlite") as db:
            stored = db.execute("SELECT payload FROM effects WHERE id='one'").fetchone()[0]
        self.assertEqual(json.loads(stored),payload)

    def test_real_disconnect_backlog_and_recovery(self):
        s = self.start()
        s.sink.stop()
        for i in range(13):
            self.assertEqual(s.submit(f"offline-{i}")[0],202)
        wait_for(lambda: s.event("offline-0")["attempts"]>=2)
        self.assertNotEqual(s.event("offline-0")["state"],"delivered")
        s.start_sink()
        for i in range(13):
            s.delivered(f"offline-{i}")
        self.assertEqual({e["id"] for e in s.effects()["effects"]},{f"offline-{i}" for i in range(13)})

    def test_sigkill_after_accepted_restart_retains_every_id(self):
        s = self.start()
        s.sink.stop()
        for i in range(9):
            self.assertEqual(s.submit(f"durable-{i}")[0],202)
        s.relay.stop(kill=True)
        s.start_relay()
        for i in range(9):
            self.assertEqual(s.event(f"durable-{i}")["id"],f"durable-{i}")
        s.start_sink()
        for i in range(9):
            s.delivered(f"durable-{i}")
        self.assertEqual(len(s.effects()["effects"]),9)

    def test_lost_ack_retries_but_business_effect_once(self):
        s = self.start()
        s.control("drop_once")
        self.assertEqual(s.submit("lost-ack")[0],202)
        s.delivered("lost-ack")
        effects = s.effects()
        self.assertEqual(len(effects["effects"]),1)
        self.assertEqual(effects["attempts"]["lost-ack"],2)
        # Receiver deduplication survives a receiver process restart too.
        s.sink.stop()
        s.start_sink()
        status,_,_ = request(s.sink_url+"/events","POST",canonical({"value":"lost-ack"}),{"Idempotency-Key":"lost-ack"})
        self.assertEqual(status,200)
        self.assertEqual(len(s.effects()["effects"]),1)
        self.assertEqual(s.effects()["attempts"]["lost-ack"],3)

    def test_kill_in_flight_after_sink_commit_recovers(self):
        s = self.start()
        s.control("commit_hang",1)
        s.submit("crash-window")
        # Observe the real sink DB while its response is intentionally blocked.
        def committed():
            with sqlite3.connect(Path(self.temp.name)/"sink.sqlite") as db:
                return db.execute("SELECT count(*) FROM effects WHERE id='crash-window'").fetchone()[0]==1
        wait_for(committed)
        self.assertEqual(s.event("crash-window")["state"],"in_flight")
        s.relay.stop(kill=True)
        time.sleep(1.05)
        s.control("ok")
        s.start_relay()
        s.delivered("crash-window")
        self.assertEqual(len(s.effects()["effects"]),1)
        self.assertEqual(s.effects()["attempts"]["crash-window"],2)

    def test_count_quota_never_evicts_unresolved(self):
        s = self.start(["--max-events","3"])
        s.sink.stop()
        for i in range(3):
            self.assertEqual(s.submit(str(i))[0],202)
        self.assertEqual(s.submit("full")[0],507)
        self.assertEqual(s.submit("0")[0],200)
        s.relay.stop(kill=True)
        s.start_relay()
        self.assertEqual(s.submit("full")[0],507)
        s.start_sink()
        for i in range(3):
            s.delivered(str(i))
        self.assertEqual(s.submit("space-returned")[0],202)
        s.delivered("space-returned")

    def test_payload_quota_and_oversize(self):
        s = self.start(["--max-payload-bytes","100","--max-event-bytes","80"])
        s.sink.stop()
        self.assertEqual(s.submit("a","x"*70)[0],202)
        self.assertEqual(s.submit("b","x"*30)[0],507)
        self.assertEqual(s.submit("c","x"*81)[0],413)
        self.assertEqual(s.event("a")["size"],72)

    def test_disk_admission_and_free_reserve_reject(self):
        s = self.start(["--disk-budget","131072"])
        self.assertEqual(s.submit("disk-full")[0],507)
        self.assertEqual(s.event("disk-full")["error"],"not found")
        s.relay.stop()
        s.extra = ["--min-free",str(1<<60)]
        s.start_relay()
        self.assertEqual(s.submit("reserve")[0],507)

    def test_permanent_failure_dead_letter_and_requeue(self):
        s = self.start(["--max-events","1"])
        s.control("permanent")
        s.submit("bad")
        wait_for(lambda: s.event("bad")["state"]=="dead_letter")
        self.assertEqual(s.event("bad")["attempts"],1)
        self.assertEqual(s.submit("next")[0],507)
        status,dead = json_request(s.url+"/v1/dead-letters")
        self.assertEqual([e["id"] for e in dead["events"]],["bad"])
        s.control("ok")
        self.assertEqual(json_request(s.url+"/v1/requeue/bad","POST",{})[0],200)
        s.delivered("bad")
        self.assertEqual(json_request(s.url+"/v1/requeue/bad","POST",{})[0],409)

    def test_retry_age_exhaustion(self):
        s = self.start(["--retry-age","0.12"])
        s.control("offline")
        s.submit("expires")
        wait_for(lambda: s.event("expires")["state"]=="dead_letter")
        self.assertIn("retry age exhausted",s.event("expires")["error"])
        self.assertGreaterEqual(s.event("expires")["attempts"],1)

    def test_429_delay_is_honored_up_to_cap(self):
        s = self.start(["--retry-cap","1.5"])
        s.control("throttle")
        s.submit("limited")
        wait_for(lambda: s.event("limited")["state"]=="pending" and s.event("limited")["attempts"]==1)
        row = s.event("limited")
        self.assertGreater(row["due"]-row["updated"],.9)
        s.control("ok")
        s.delivered("limited")

    def test_receipt_limit_and_ttl_are_explicit_windows(self):
        s = self.start(["--receipt-limit","2","--receipt-ttl","0.4"])
        for i in range(3):
            s.submit(str(i))
            s.delivered(str(i))
        self.assertEqual(json_request(s.url+"/v1/events/0")[0],404)
        self.assertEqual(s.submit("2")[0],200)
        time.sleep(.45)
        # Pruning runs on submit/finish; the sink remains independently idempotent.
        self.assertEqual(s.submit("2")[0],202)
        s.delivered("2")
        self.assertEqual(len(s.effects()["effects"]),3)

    def test_directory_lock_and_clean_shutdown_restart(self):
        s = self.start()
        result = subprocess.run([sys.executable,"-m","relay","serve","--data-dir",str(Path(self.temp.name)/"queue"),
                                 "--upstream",s.sink_url+"/events","--port","0"],cwd=ROOT,capture_output=True,timeout=4)
        self.assertNotEqual(result.returncode,0)
        self.assertIn(b"already owned",result.stderr)
        s.relay.stop()
        self.assertEqual(s.relay.process.returncode,0)
        s.start_relay()
        s.submit("after-shutdown")
        s.delivered("after-shutdown")

    def test_bad_input_does_not_enter_queue(self):
        s = self.start()
        for body in (b'{"event_id":"x","payload":NaN}',b'{"event_id":"x","event_id":"y","payload":1}',
                     b'{"event_id":"bad id","payload":1}',b'{}',b'{'):
            self.assertEqual(request(s.url+"/v1/events","POST",body)[0],400)
        self.assertEqual(json_request(s.url+"/v1/stats")[1]["states"],{})

    def test_receiver_conflicting_payload_does_not_apply(self):
        s = self.start()
        s.submit("same",1)
        s.delivered("same")
        self.assertEqual(request(s.sink_url+"/events","POST",b"2",{"Idempotency-Key":"same"})[0],409)
        self.assertEqual(len(s.effects()["effects"]),1)

    def test_timeout_after_commit_recovers_without_duplicate_effect(self):
        s = self.start()
        s.control("ok",.6)
        s.submit("slow-ack")
        wait_for(lambda: s.event("slow-ack")["attempts"]>=2)
        s.control("ok",0)
        s.delivered("slow-ack")
        effects = s.effects()
        self.assertEqual(len(effects["effects"]),1)
        self.assertGreaterEqual(effects["attempts"]["slow-ack"],2)

    def test_shutdown_closes_partial_request_and_releases_lock(self):
        s = self.start()
        with socket.create_connection(("127.0.0.1",s.relay_port),timeout=2) as sock:
            sock.sendall(f"POST /v1/events HTTP/1.0\r\nHost: 127.0.0.1:{s.relay_port}\r\nContent-Length: 100\r\n\r\nx".encode())
            time.sleep(.05)
            started = time.monotonic()
            s.relay.stop()
            self.assertLess(time.monotonic()-started,3)
        self.assertEqual(s.relay.process.returncode,0)
        s.start_relay()
        s.submit("after-partial")
        s.delivered("after-partial")


class StoreFaultTests(unittest.TestCase):
    def test_stale_claim_token_cannot_override_new_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            self.addCleanup(store.close)
            store.submit("a",b"1")
            old = store.claim(.01)
            time.sleep(.02)
            new = store.claim(2)
            self.assertFalse(store.finish("a",old["token"],"delivered"))
            self.assertTrue(store.finish("a",new["token"],"delivered"))

    def test_actual_sqlite_page_limit_failure_rolls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory,disk_budget=16*1024*1024)
            self.addCleanup(store.close)
            count = store.db.execute("PRAGMA page_count").fetchone()[0]
            store.db.execute(f"PRAGMA max_page_count={count}")
            with self.assertRaises(sqlite3.OperationalError):
                store.submit("cannot-fit",b"x"*128000)
            self.assertIsNone(store.get("cannot-fit"))
            self.assertFalse(store.db.in_transaction)
            self.assertEqual(store.submit("small",b"1")[0]["id"],"small")

    def test_commit_error_never_returns_success(self):
        # Supplemental deterministic failure injection at the actual production Store boundary.
        class FailCommit:
            def __init__(self,db):
                self.db = db
            def __getattr__(self,name):
                return getattr(self.db,name)
            def execute(self,sql,args=()):
                if sql=="COMMIT":
                    raise sqlite3.OperationalError("injected commit failure")
                return self.db.execute(sql,args)
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            original = store.db
            store.db = FailCommit(original)
            with self.assertRaises(sqlite3.OperationalError):
                store.submit("not-accepted",b"1")
            self.assertIsNone(store.get("not-accepted"))
            store.db = original
            store.close()


if __name__=="__main__":
    unittest.main()


class DNSIndependentStartupTests(unittest.TestCase):
    def test_loopback_server_startup_does_not_resolve_hostnames(self):
        from unittest.mock import patch
        from relay.service import Server,LocalHandler
        # A resolver outage must not prevent the numeric loopback listener from binding.
        with patch("socket.getfqdn",side_effect=AssertionError("unexpected startup DNS lookup")):
            with Server(("127.0.0.1",0),LocalHandler) as server:
                self.assertEqual(server.server_name,"127.0.0.1")
                self.assertGreater(server.server_port,0)
                self.assertEqual(server.server_address,("127.0.0.1",server.server_port))
