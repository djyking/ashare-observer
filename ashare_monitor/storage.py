"""Transactional local state and paged scan history; never a brokerage ledger."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "research.sqlite3"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS scans (id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL, payload TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA busy_timeout=10000")
            with db:
                yield db
        finally:
            db.close()

    def load(self):
        with self.connect() as db:
            row = db.execute("SELECT value FROM state WHERE key='app'").fetchone()
        return json.loads(row[0]) if row else None

    def save(self, value, history=None):
        with self.connect() as db:
            db.execute("INSERT INTO state(key,value) VALUES('app',?) ON CONFLICT(key) "
                       "DO UPDATE SET value=excluded.value", (encode(value),))
            if history is not None:
                db.execute("INSERT INTO scans(created_at,payload) VALUES(?,?)",
                           (history["created_at"], encode(history)))
                # Scan reports are bounded; paper orders/trades are separate and never pruned.
                db.execute("DELETE FROM scans WHERE id NOT IN "
                           "(SELECT id FROM scans ORDER BY id DESC LIMIT 2000)")

    def history(self, page=1, page_size=30):
        page_size = max(1, min(30, int(page_size)))
        with self.connect() as db:
            total = db.execute("SELECT COUNT(*) FROM scans").fetchone()[0]
            pages = max(1, (total + page_size - 1) // page_size)
            page = max(1, min(pages, int(page)))
            rows = db.execute("SELECT id,payload FROM scans ORDER BY id DESC LIMIT ? OFFSET ?",
                              (page_size, (page - 1) * page_size)).fetchall()
        return {"items": [{**json.loads(row[1]), "id": row[0]} for row in rows],
                "total": total, "page": page, "pages": pages, "page_size": page_size}
