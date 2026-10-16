"""All queue state changes are serialized transactions, separate from network I/O."""
import hashlib
import os
import shutil
import sqlite3
import threading
import time
import uuid
from pathlib import Path


class CapacityError(Exception):
    pass


class ConflictError(Exception):
    pass


class Store:
    def __init__(self, directory, *, max_events=1000, max_payload_bytes=8*1024*1024,
                 disk_budget=64*1024*1024, min_free=16*1024*1024,
                 receipt_limit=10000, receipt_ttl=86400):
        import fcntl
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock_file = (self.directory / "owner.lock").open("a")
        try:
            fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock_file.close()
            raise RuntimeError("data directory is already owned by another relay") from None
        self.lock = threading.RLock()
        self.max_events, self.max_payload_bytes = max_events, max_payload_bytes
        self.disk_budget, self.min_free = disk_budget, min_free
        self.receipt_limit, self.receipt_ttl = receipt_limit, receipt_ttl
        self.db = sqlite3.connect(self.directory / "queue.sqlite", check_same_thread=False,
                                  isolation_level=None, timeout=2)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA fullfsync=ON")
        self.db.execute("PRAGMA checkpoint_fullfsync=ON")
        self.db.execute("PRAGMA busy_timeout=2000")
        # Leave room for WAL, SHM and state transitions. This is not a filesystem quota.
        self.db.execute(f"PRAGMA max_page_count={max(128, disk_budget // 8192)}")
        self.db.execute("""CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY, digest TEXT NOT NULL, payload BLOB,
            size INTEGER NOT NULL, state TEXT NOT NULL,
            created REAL NOT NULL, retry_started REAL NOT NULL, updated REAL NOT NULL,
            due REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
            lease_until REAL, token TEXT, error TEXT)""")
        self.db.execute("CREATE INDEX IF NOT EXISTS ready ON events(state,due,created)")
        self.db.execute("CREATE INDEX IF NOT EXISTS retention ON events(state,updated)")
        # Exclusive process ownership permits immediate recovery, including unexpired leases.
        self.db.execute("UPDATE events SET state='pending', token=NULL, lease_until=NULL WHERE state='in_flight'")
        self.checkpoint()

    def checkpoint(self):
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def disk_bytes(self):
        return sum(p.stat().st_size for p in self.directory.glob("queue.sqlite*") if p.is_file())

    def _prune(self, now):
        self.db.execute("DELETE FROM events WHERE state='delivered' AND updated<?", (now-self.receipt_ttl,))
        self.db.execute("""DELETE FROM events WHERE id IN (
            SELECT id FROM events WHERE state='delivered' ORDER BY updated DESC,id LIMIT -1 OFFSET ?)
            """, (self.receipt_limit,))

    def submit(self, event_id, payload):
        digest = hashlib.sha256(payload).hexdigest()
        now = time.time()
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                self._prune(now)
                row = self.db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
                if row:
                    if row["digest"] != digest:
                        raise ConflictError("event ID already exists with different content")
                    self.db.execute("COMMIT")
                    self.checkpoint()
                    return self._public(row), True
                count, size = self.db.execute("SELECT count(*),coalesce(sum(size),0) FROM events WHERE state!='delivered'").fetchone()
                if count >= self.max_events or size + len(payload) > self.max_payload_bytes:
                    raise CapacityError("pending/dead-letter quota exhausted")
                # Conservative admission reserve for page/index amplification and state updates.
                reserve = 256*1024 + len(payload)*4
                if self.disk_bytes() + reserve > self.disk_budget:
                    raise CapacityError("database disk admission budget exhausted")
                if shutil.disk_usage(self.directory).free < self.min_free + reserve:
                    raise CapacityError("free disk reserve reached")
                self.db.execute("""INSERT INTO events
                    (id,digest,payload,size,state,created,retry_started,updated,due)
                    VALUES (?,?,?,?,'pending',?,?,?,?)""",
                    (event_id,digest,payload,len(payload),now,now,now,now))
                self.db.execute("COMMIT")
            except BaseException:
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK")
                raise
            # A committed event remains accepted even if checkpointing is temporarily busy.
            self.checkpoint()
            return self.get(event_id), False

    @staticmethod
    def _public(row):
        return {k: row[k] for k in ("id","digest","size","state","created","updated","attempts","due","error")}

    def get(self, event_id):
        with self.lock:
            row = self.db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
            return self._public(row) if row else None

    def claim(self, lease_seconds):
        now = time.time()
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                self.db.execute("UPDATE events SET state='pending',token=NULL,lease_until=NULL WHERE state='in_flight' AND lease_until<=?", (now,))
                row = self.db.execute("SELECT * FROM events WHERE state='pending' AND due<=? ORDER BY due,created,id LIMIT 1", (now,)).fetchone()
                if row is None:
                    self.db.execute("COMMIT")
                    return None
                token = uuid.uuid4().hex
                self.db.execute("UPDATE events SET state='in_flight',token=?,lease_until=?,attempts=attempts+1,updated=? WHERE id=?",
                                (token,now+lease_seconds,now,row["id"]))
                self.db.execute("COMMIT")
                self.checkpoint()
                result = dict(row)
                result.update(token=token, attempts=row["attempts"]+1)
                return result
            except BaseException:
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK")
                raise

    def finish(self, event_id, token, state, error=None, delay=0):
        now = time.time()
        with self.lock:
            changed = self.db.execute("""UPDATE events SET state=?,updated=?,due=?,error=?,
                token=NULL,lease_until=NULL,payload=CASE WHEN ?='delivered' THEN NULL ELSE payload END,
                size=CASE WHEN ?='delivered' THEN 0 ELSE size END
                WHERE id=? AND state='in_flight' AND token=?""",
                (state,now,now+delay,error,state,state,event_id,token)).rowcount
            self._prune(now)
            self.checkpoint()
            return changed == 1

    def requeue(self, event_id):
        now = time.time()
        with self.lock:
            changed = self.db.execute("""UPDATE events SET state='pending',due=?,updated=?,
                retry_started=?,attempts=0,error=NULL WHERE id=? AND state='dead_letter'""",
                (now,now,now,event_id)).rowcount
            self.checkpoint()
            return changed == 1

    def stats(self):
        with self.lock:
            counts = {r[0]: r[1] for r in self.db.execute("SELECT state,count(*) FROM events GROUP BY state")}
            oldest = self.db.execute("SELECT min(created) FROM events WHERE state!='delivered'").fetchone()[0]
            size = self.db.execute("SELECT coalesce(sum(size),0) FROM events WHERE state!='delivered'").fetchone()[0]
            return {"states": counts, "retained_payload_bytes":size, "disk_bytes": self.disk_bytes(),
                    "oldest_unresolved_age_s": max(0,time.time()-oldest) if oldest else 0,
                    "disk_admission_budget_bytes":self.disk_budget,
                    "dedup_receipt_limit":self.receipt_limit,"dedup_receipt_ttl_s":self.receipt_ttl}

    def dead_letters(self):
        with self.lock:
            return [self._public(r) for r in self.db.execute("SELECT * FROM events WHERE state='dead_letter' ORDER BY created LIMIT 100")]

    def close(self):
        with self.lock:
            self.db.close()
            self.lock_file.close()
