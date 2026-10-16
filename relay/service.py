import email.utils
import http.client
import json
import random
import re
import signal
import socket
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlsplit, unquote

from .store import Store, CapacityError, ConflictError


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",",":"), allow_nan=False, ensure_ascii=True).encode()


def _reject_constant(value):
    raise ValueError("non-finite JSON number")


def _unique_object(pairs):
    result = {}
    for key,value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def parse_json(body):
    return json.loads(body, parse_constant=_reject_constant, object_pairs_hook=_unique_object)


class Server(HTTPServer):
    allow_reuse_address = True
    request_queue_size = 32

    def get_request(self):
        sock, address = super().get_request()
        sock.settimeout(2)
        return sock,address

    def process_request(self,request,address):
        self.active_socket = request
        timer = threading.Timer(2,lambda: self.abort_socket(request))
        timer.daemon = True
        timer.start()
        try:
            super().process_request(request,address)
        finally:
            timer.cancel()
            self.active_socket = None

    def abort_active(self):
        sock = getattr(self,"active_socket",None)
        self.abort_socket(sock)

    @staticmethod
    def abort_socket(sock):
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


class Relay:
    def __init__(self, directory, upstream, *, port=8080, timeout=2, retry_base=.25,
                 retry_cap=30, retry_age=86400, max_event_bytes=65536, **store_args):
        parts = urlsplit(upstream)
        if parts.scheme not in ("http","https") or not parts.hostname or parts.username or parts.password or parts.fragment:
            raise ValueError("upstream must be a configured http(s) URL without credentials or fragment")
        # Validate port eagerly, before creating durable state.
        parts.port
        self.upstream = parts
        self.timeout, self.retry_base, self.retry_cap, self.retry_age = timeout,retry_base,retry_cap,retry_age
        self.max_event_bytes = max_event_bytes
        self.store = Store(directory, **store_args)
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.metrics = {"attempts":0,"delivered":0,"retry":0,"dead_letter":0,"rejected":0,"storage_errors":0}
        self.worker_error = None
        relay = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, code, value):
                body = canonical(value)
                self.send_response(code)
                self.send_header("Content-Type","application/json")
                self.send_header("Content-Length",str(len(body)))
                self.send_header("Connection","close")
                self.end_headers()
                try:
                    self.wfile.write(body)
                except OSError:
                    pass  # Committed submission can outlive a disconnected caller.

            def do_GET(self):
                if self.path == "/health":
                    return self.reply(503 if relay.worker_error else 200, {"ok":relay.worker_error is None})
                if self.path == "/v1/stats":
                    return self.reply(200, {**relay.store.stats(),"process_counters":dict(relay.metrics),"worker_error":relay.worker_error})
                if self.path == "/v1/dead-letters":
                    return self.reply(200,{"events":relay.store.dead_letters()})
                if self.path.startswith("/v1/events/"):
                    row = relay.store.get(unquote(self.path[len("/v1/events/"):]))
                    return self.reply(200 if row else 404,row or {"error":"not found"})
                self.reply(404,{"error":"not found"})

            def do_POST(self):
                if self.path.startswith("/v1/requeue/"):
                    ok = relay.store.requeue(unquote(self.path[len("/v1/requeue/"):]))
                    relay.wake.set()
                    return self.reply(200 if ok else 409,{"requeued":ok})
                if self.path != "/v1/events":
                    return self.reply(404,{"error":"not found"})
                try:
                    lengths = self.headers.get_all("Content-Length",[])
                    if self.headers.get("Transfer-Encoding") or len(lengths)!=1 or not re.fullmatch(r"[0-9]{1,9}",lengths[0]):
                        return self.reply(400,{"error":"one valid Content-Length required; no Transfer-Encoding"})
                    length = int(lengths[0])
                    if length > relay.max_event_bytes*6+1024:
                        return self.reply(413,{"error":"request too large"})
                    raw = self.rfile.read(length)
                    if len(raw)!=length:
                        return self.reply(400,{"error":"incomplete body"})
                    event = parse_json(raw)
                    if not isinstance(event,dict) or set(event)!={"event_id","payload"}:
                        raise ValueError("expected event_id and payload")
                    event_id = event["event_id"]
                    if not isinstance(event_id,str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}",event_id):
                        raise ValueError("invalid event ID")
                    payload = canonical(event["payload"])
                    if len(payload)>relay.max_event_bytes:
                        return self.reply(413,{"error":"canonical payload too large"})
                    row,duplicate = relay.store.submit(event_id,payload)
                    relay.wake.set()
                    self.reply(200 if duplicate else 202,{"event":row,"duplicate":duplicate})
                except ConflictError as exc:
                    self.reply(409,{"error":str(exc)})
                except CapacityError as exc:
                    relay.metrics["rejected"] += 1
                    self.reply(507,{"error":str(exc)})
                except (ValueError,UnicodeError,RecursionError):
                    self.reply(400,{"error":"invalid JSON event"})
                except (sqlite3.Error,OSError):
                    relay.metrics["storage_errors"] += 1
                    self.reply(503,{"error":"storage unavailable; acceptance unknown, retry same ID"})

        try:
            self.server = Server(("127.0.0.1",port),Handler)
        except BaseException:
            self.store.close()
            raise
        self.server.timeout = .1

    def deliver(self, event):
        parts = self.upstream
        cls = http.client.HTTPSConnection if parts.scheme=="https" else http.client.HTTPConnection
        connection = cls(parts.hostname,parts.port,timeout=self.timeout)
        expired = threading.Event()
        def abort():
            expired.set()
            sock = connection.sock
            if sock:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        timer = threading.Timer(self.timeout,abort)
        timer.daemon = True
        timer.start()
        try:
            connection.connect()
            if expired.is_set():
                raise TimeoutError("delivery deadline exceeded")
            connection.request("POST",(parts.path or "/")+("?"+parts.query if parts.query else ""),event["payload"],
                               {"Content-Type":"application/json","Idempotency-Key":event["id"]})
            response = connection.getresponse()
            # A status acknowledgment is sufficient; never buffer an unbounded response body.
            return response.status,response.getheader("Retry-After")
        finally:
            timer.cancel()
            connection.close()

    def retry_after(self, value):
        if value is None:
            return 0
        try:
            delay = float(value)
        except ValueError:
            try:
                delay = email.utils.parsedate_to_datetime(value).timestamp()-time.time()
            except (ValueError,TypeError,OverflowError):
                return 0
        return max(0,min(delay,self.retry_cap))

    def work(self):
        while not self.stop.is_set():
            try:
                event = self.store.claim(self.timeout+2)
                if event is None:
                    self.wake.wait(.05)
                    self.wake.clear()
                    continue
                self.metrics["attempts"] += 1
                try:
                    status,after = self.deliver(event)
                    error = f"HTTP {status}"
                except (OSError,http.client.HTTPException) as exc:
                    status,after,error = 0,None,type(exc).__name__
                if 200<=status<300:
                    state,delay,error = "delivered",0,None
                elif status in (0,408,429) or 500<=status<600:
                    delay = max(self.retry_after(after),random.uniform(.5,1)*min(self.retry_cap,self.retry_base*2**min(event["attempts"]-1,30)))
                    if time.time()+delay-event["retry_started"] >= self.retry_age:
                        state,error = "dead_letter",f"retry age exhausted: {error}"
                    else:
                        state = "pending"
                else:
                    state,delay = "dead_letter",0
                if self.store.finish(event["id"],event["token"],state,error,delay):
                    self.metrics["retry" if state=="pending" else state] += 1
                self.worker_error = None
            except (sqlite3.Error,OSError) as exc:
                # Never drop an unresolved claim on storage failure; lease recovery retries it.
                self.metrics["storage_errors"] += 1
                self.worker_error = type(exc).__name__
                self.stop.wait(.1)
            except Exception as exc:
                self.worker_error = type(exc).__name__
                self.stop.set()

    def run(self):
        worker = threading.Thread(target=self.work,name="delivery")
        worker.start()
        try:
            while not self.stop.is_set():
                self.server.handle_request()
        finally:
            self.stop.set()
            self.wake.set()
            worker.join()  # Active socket is bounded by timeout for normal local peers.
            self.server.server_close()
            self.store.close()

    def signal_stop(self, *_):
        self.stop.set()
        self.wake.set()
        self.server.abort_active()
