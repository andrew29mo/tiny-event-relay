"""Local demonstration sink: dedup and business effect share one durable transaction.

The unauthenticated /control fault injector is for loopback experiments only.
"""
import argparse
import hashlib
import json
import signal
import socket
import sqlite3
import time
from relay.service import Server, LocalHandler, canonical, parse_json


class Receiver:
    def __init__(self, db_path, port=8081, delay=0):
        self.db = sqlite3.connect(db_path,isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA fullfsync=ON")
        self.db.execute("PRAGMA checkpoint_fullfsync=ON")
        self.db.execute("CREATE TABLE IF NOT EXISTS receipts (id TEXT PRIMARY KEY,digest TEXT NOT NULL)")
        # Deliberately no uniqueness constraint on effect.id: dedup must protect the append.
        self.db.execute("CREATE TABLE IF NOT EXISTS effects (seq INTEGER PRIMARY KEY,id TEXT NOT NULL,digest TEXT NOT NULL,payload BLOB NOT NULL,applied REAL NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS attempts (id TEXT PRIMARY KEY,n INTEGER NOT NULL)")
        self.mode,self.delay,self.running = "ok",delay,True
        # Measurement-only observations taken AFTER the business transaction commits.
        # On receiver restart historical commit completion times are unavailable.
        self.commit_times = {}
        self.commit_monotonic = {}
        sink = self

        class Handler(LocalHandler):
            def log_message(self,*args):
                pass

            def reply(self,status,value):
                data = canonical(value)
                self.send_response(status)
                self.send_header("Content-Length",str(len(data)))
                self.send_header("Content-Type","application/json")
                self.send_header("Connection","close")
                if status==429:
                    self.send_header("Retry-After","1")
                self.end_headers()
                try:
                    self.wfile.write(data)
                except OSError:
                    pass

            def do_GET(self):
                if self.path=="/health":
                    return self.reply(200,{"ok":True})
                if self.path=="/effects":
                    rows = sink.db.execute("SELECT id,digest,applied FROM effects ORDER BY id").fetchall()
                    attempts = dict(sink.db.execute("SELECT id,n FROM attempts"))
                    return self.reply(200,{"effects":[{"id":r[0],"digest":r[1],"transaction_recorded":r[2],
                                                       "committed":sink.commit_times.get(r[0]),
                                                       "committed_monotonic":sink.commit_monotonic.get(r[0])} for r in rows],"attempts":attempts})
                self.reply(404,{})

            def do_POST(self):
                length = int(self.headers.get("Content-Length","0"))
                if not 0<=length<=512*1024:
                    return self.reply(413,{})
                body = self.rfile.read(length)
                if self.path=="/control":
                    value = parse_json(body)
                    if value.get("mode") not in ("ok","offline","permanent","throttle","drop_once","commit_hang"):
                        return self.reply(400,{})
                    sink.mode = value["mode"]
                    sink.delay = float(value.get("delay",0))
                    return self.reply(200,{"mode":sink.mode})
                if self.path!="/events":
                    return self.reply(404,{})
                event_id = self.headers.get("Idempotency-Key")
                if not event_id:
                    return self.reply(400,{"error":"Idempotency-Key required"})
                if sink.mode=="offline":
                    return self.reply(503,{})
                if sink.mode=="permanent":
                    return self.reply(400,{})
                if sink.mode=="throttle":
                    return self.reply(429,{})
                digest = hashlib.sha256(body).hexdigest()
                sink.db.execute("BEGIN IMMEDIATE")
                try:
                    old = sink.db.execute("SELECT digest FROM receipts WHERE id=?",(event_id,)).fetchone()
                    if old and old[0]!=digest:
                        sink.db.execute("ROLLBACK")
                        return self.reply(409,{})
                    sink.db.execute("INSERT INTO attempts(id,n) VALUES (?,1) ON CONFLICT(id) DO UPDATE SET n=n+1",(event_id,))
                    if old is None:
                        sink.db.execute("INSERT INTO receipts VALUES (?,?)",(event_id,digest))
                        sink.db.execute("INSERT INTO effects(id,digest,payload,applied) VALUES (?,?,?,?)",(event_id,digest,body,time.time()))
                    sink.db.execute("COMMIT")
                    if old is None:
                        sink.commit_monotonic[event_id] = time.monotonic()
                        sink.commit_times[event_id] = time.time()
                except BaseException:
                    if sink.db.in_transaction:
                        sink.db.execute("ROLLBACK")
                    raise
                if (sink.mode=="drop_once" and old is None) or sink.mode=="commit_hang":
                    if sink.mode=="commit_hang":
                        time.sleep(sink.delay or 2)
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.close_connection = True
                    return
                time.sleep(sink.delay)
                self.reply(200,{"duplicate":old is not None})

        self.server = Server(("127.0.0.1",port),Handler)
        self.server.timeout = .1

    def run(self):
        try:
            while self.running:
                self.server.handle_request()
        finally:
            self.server.server_close()
            self.db.close()

    def stop(self,*_):
        self.running = False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db",required=True)
    parser.add_argument("--port",type=int,default=8081)
    parser.add_argument("--delay",type=float,default=0)
    args = parser.parse_args()
    receiver = Receiver(args.db,args.port,args.delay)
    signal.signal(signal.SIGTERM,receiver.stop)
    signal.signal(signal.SIGINT,receiver.stop)
    receiver.run()


if __name__=="__main__":
    main()
