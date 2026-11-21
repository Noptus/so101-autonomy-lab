import json
import sqlite3
import threading
import time
from pathlib import Path


class Memory:
    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o700)
        self.db = sqlite3.connect(directory / "lab.sqlite3", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, ts REAL, kind TEXT, data TEXT)"
        )
        self.db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, data TEXT)")
        self.lock = threading.RLock()
        self.secrets = set()

    def clean(self, value):
        text = json.dumps(value, default=str, allow_nan=False)
        for secret in self.secrets:
            if secret:
                text = text.replace(secret, "[REDACTED]")
        return json.loads(text)

    def add(self, kind, data):
        with self.lock:
            self.db.execute(
                "INSERT INTO events(ts,kind,data) VALUES(?,?,?)",
                (time.time(), kind, json.dumps(self.clean(data))),
            )
            self.db.commit()

    def events(self, limit=100, after=0):
        with self.lock:
            rows = self.db.execute(
                "SELECT id,ts,kind,data FROM events WHERE id>? ORDER BY id DESC LIMIT ?",
                (after, min(limit, 1000)),
            ).fetchall()
        return [dict(id=r[0], ts=r[1], kind=r[2], data=json.loads(r[3])) for r in rows]

    def save(self, key, value):
        with self.lock:
            self.db.execute(
                "INSERT OR REPLACE INTO settings VALUES(?,?)", (key, json.dumps(self.clean(value)))
            )
            self.db.commit()

    def get(self, key, default=None):
        with self.lock:
            row = self.db.execute("SELECT data FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def close(self):
        self.db.close()
