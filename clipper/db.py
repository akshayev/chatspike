"""SQLite store (WAL) - the single source of truth for clips, events and AI calls.
Every clip row keeps a few indexed columns plus the full record as JSON in `data`.

Clip status flow:
  rendered -> gate: auto | review | rejected
  review   -> approved (Discord / CLI) | rejected
  auto/approved -> uploading -> uploaded -> submitted | submit_failed
                               \\-> upload_failed
  any waiting state -> stale (too old to post)
"""
import json, sqlite3, threading, time
from .common import ROOT, log

L = log("db")
DB_PATH = ROOT / "data" / "clipper.db"
_lock = threading.RLock()
_conn = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS clips (
  id TEXT PRIMARY KEY,
  channel TEXT NOT NULL,
  campaign_id TEXT,
  status TEXT NOT NULL,
  score REAL,
  spike_at REAL,
  created REAL NOT NULL,
  uploaded_at REAL,
  data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS clips_status ON clips(status);
CREATE INDEX IF NOT EXISTS clips_uploaded ON clips(uploaded_at);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  channel TEXT, t REAL, kind TEXT, data TEXT
);
CREATE TABLE IF NOT EXISTS ai_calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  t REAL, tier TEXT, model TEXT, purpose TEXT,
  tokens_in INTEGER, tokens_out INTEGER, ms INTEGER, ok INTEGER
);
"""


def conn():
    global _conn
    with _lock:
        if _conn is None:
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            _conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.execute("PRAGMA synchronous=NORMAL")
            _conn.executescript(SCHEMA)
            _conn.commit()
        return _conn


def save_clip(item):
    """Insert or replace a clip record (dict with at least id, channel, status, created)."""
    with _lock:
        c = conn()
        c.execute("""INSERT INTO clips(id, channel, campaign_id, status, score, spike_at, created, uploaded_at, data)
                     VALUES(?,?,?,?,?,?,?,?,?)
                     ON CONFLICT(id) DO UPDATE SET channel=excluded.channel, campaign_id=excluded.campaign_id,
                       status=excluded.status, score=excluded.score, spike_at=excluded.spike_at,
                       created=excluded.created, uploaded_at=excluded.uploaded_at, data=excluded.data""",
                  (item["id"], item["channel"], item.get("campaign_id"), item["status"], item.get("score"),
                   (item.get("event") or {}).get("spike_at"), item["created"], item.get("uploaded_at"),
                   json.dumps(item, ensure_ascii=False)))
        c.commit()
    return item


def get_clip(cid):
    with _lock:
        row = conn().execute("SELECT data FROM clips WHERE id=?", (cid,)).fetchone()
    return json.loads(row[0]) if row else None


def update_clip(cid, **fields):
    with _lock:
        item = get_clip(cid)
        if item is None:
            raise KeyError(cid)
        item.update(fields)
        return save_clip(item)


def clips(status=None, channel=None, since=None, limit=500):
    q, args = "SELECT data FROM clips WHERE 1=1", []
    if status:
        statuses = [status] if isinstance(status, str) else list(status)
        q += f" AND status IN ({','.join('?' * len(statuses))})"
        args += statuses
    if channel:
        q += " AND channel=?"; args.append(channel)
    if since:
        q += " AND created>=?"; args.append(since)
    q += " ORDER BY created DESC LIMIT ?"; args.append(limit)
    with _lock:
        rows = conn().execute(q, args).fetchall()
    return [json.loads(r[0]) for r in rows]


def upload_times(since):
    with _lock:
        rows = conn().execute("SELECT uploaded_at FROM clips WHERE uploaded_at IS NOT NULL AND uploaded_at>=? "
                              "ORDER BY uploaded_at", (since,)).fetchall()
    return [r[0] for r in rows]


def posted_spikes(channel, since):
    """spike_at of clips from this channel that were posted or are about to be."""
    with _lock:
        rows = conn().execute("SELECT spike_at FROM clips WHERE channel=? AND created>=? AND status IN "
                              "('auto','approved','uploading','uploaded','submitted','submit_failed')",
                              (channel, since)).fetchall()
    return [r[0] for r in rows if r[0]]


def log_event(channel, kind, data=None):
    with _lock:
        c = conn()
        c.execute("INSERT INTO events(channel, t, kind, data) VALUES(?,?,?,?)",
                  (channel, time.time(), kind, json.dumps(data or {}, ensure_ascii=False)))
        c.commit()


def import_queue_dir(qdir):
    """One-time migration: pull legacy queue/*.json records into the DB."""
    n = 0
    for f in sorted(qdir.glob("*.json")):
        try:
            item = json.loads(f.read_text())
            if get_clip(item["id"]) is None:
                item.setdefault("created", f.stat().st_mtime)
                save_clip(item)
                n += 1
        except Exception as e:
            L.warning("skip %s: %s", f.name, e)
    if n:
        L.info("imported %d legacy queue records into the DB", n)
