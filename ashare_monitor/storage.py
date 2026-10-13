"""Transactional local state and paged scan history; never a brokerage ledger."""
import json
import sqlite3
from uuid import uuid4
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
                CREATE TABLE IF NOT EXISTS scan_details (id INTEGER PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS experiments (id TEXT PRIMARY KEY, kind TEXT NOT NULL,
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

    def save(self, value, history=None, details=None, archive=None):
        with self.connect() as db:
            if archive:
                db.execute("INSERT INTO experiments(id,kind,created_at,payload) VALUES(?,?,?,?)",
                           (archive["id"], archive["kind"], archive["created_at"], encode(archive)))
            db.execute("INSERT INTO state(key,value) VALUES('app',?) ON CONFLICT(key) "
                       "DO UPDATE SET value=excluded.value", (encode(value),))
            if history is not None:
                cursor = db.execute("INSERT INTO scans(created_at,payload) VALUES(?,?)",
                                    (history["created_at"], encode(history)))
                if details is not None:
                    db.execute("INSERT INTO scan_details(id,payload) VALUES(?,?)", (cursor.lastrowid, encode(details)))
                # Scan reports are bounded; paper orders/trades are separate and never pruned.
                db.execute("DELETE FROM scans WHERE id NOT IN "
                           "(SELECT id FROM scans ORDER BY id DESC LIMIT 2000)")
                db.execute("DELETE FROM scan_details WHERE id NOT IN (SELECT id FROM scans)")

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

    def history_detail(self, scan_id):
        with self.connect() as db:
            row = db.execute("SELECT s.id,s.payload,d.payload FROM scans s LEFT JOIN scan_details d ON s.id=d.id WHERE s.id=?",
                             (int(scan_id),)).fetchone()
        if row is None:
            raise KeyError("研究记录不存在或已超过保留范围。")
        return {**json.loads(row[1]), "id": row[0], "details": json.loads(row[2]) if row[2] else None}

    def create_experiment(self, kind, name, config, created_at):
        item = {"id": uuid4().hex, "kind": kind, "name": name, "config": config,
                "created_at": created_at, "status": "running", "archived": False,
                "report": None, "error": None}
        with self.connect() as db:
            db.execute("INSERT INTO experiments VALUES(?,?,?,?)", (item["id"], kind, created_at, encode(item)))
        return item

    def experiment(self, experiment_id, kind=None):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM experiments WHERE id=?", (experiment_id,)).fetchone()
        if row is None:
            raise KeyError("实验不存在。")
        item = json.loads(row[0])
        if kind and item["kind"] != kind:
            raise KeyError("实验类型不匹配。")
        return item

    def update_experiment(self, experiment_id, changes):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM experiments WHERE id=?", (experiment_id,)).fetchone()
            if row is None:
                raise KeyError("实验不存在。")
            item = {**json.loads(row[0]), **changes}
            db.execute("UPDATE experiments SET payload=? WHERE id=?", (encode(item), experiment_id))
        return item

    def experiments(self, kind, page=1, page_size=30):
        page_size = max(1, min(30, int(page_size)))
        with self.connect() as db:
            total = db.execute("SELECT COUNT(*) FROM experiments WHERE kind=?", (kind,)).fetchone()[0]
            pages = max(1, (total + page_size - 1) // page_size)
            page = max(1, min(pages, int(page)))
            rows = db.execute("SELECT json_remove(payload,'$.report','$.dataset'), "
                              "json_extract(payload,'$.report.metrics'), "
                              "json_extract(payload,'$.report.quality') FROM experiments "
                              "WHERE kind=? ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?",
                              (kind, page_size, (page - 1) * page_size)).fetchall()
        items = []
        for row in rows:
            item = json.loads(row[0])
            item["metrics"] = json.loads(row[1]) if row[1] else {}
            item["quality"] = row[2]
            items.append(item)
        return {"items": items, "total": total, "page": page, "pages": pages, "page_size": page_size}

    def recover_research(self):
        # A process restart must not leave a lost in-memory worker running forever.
        with self.connect() as db:
            for row in db.execute("SELECT id,payload FROM experiments WHERE kind='research' "
                                  "AND json_extract(payload,'$.status')='running'").fetchall():
                item = json.loads(row[1])
                if item["status"] == "running":
                    item.update(status="failed", error="服务重启中断了本次研究，请新建实验重试；已完成报告不受影响。")
                    db.execute("UPDATE experiments SET payload=? WHERE id=?", (encode(item), row[0]))
