"""Operator tools shared by the MCP server (Claude Code) and the dashboard.

Read tools return grounded data from the DB, the clipper heartbeat, the vault and the log.
Claude never changes anything directly: request_action() only queues a proposal in
data/actions.json; the dashboard (or `run.py --actions`) asks the user and applies it."""
import json, sqlite3, time, uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "clipper.db"
VAULT = ROOT / "vault"
ACTIONS = ROOT / "data" / "actions.json"
KINDS = ("approve", "reject", "set_title", "pause", "resume")


def _db():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def _clips(where="1=1", args=(), limit=30):
    with _db() as c:
        rows = c.execute(f"SELECT data FROM clips WHERE {where} ORDER BY created DESC LIMIT ?", (*args, limit)).fetchall()
    return [json.loads(r["data"]) for r in rows]


def _brief(c):
    g = c.get("gate", {})
    return {"id": c["id"], "channel": c["channel"], "status": c["status"], "score": c.get("score"),
            "title": c.get("title"), "hook": c.get("hook"), "duration": c.get("duration"),
            "why": (g.get("hard", []) + g.get("soft", []))[:3], "claude": c.get("claude"),
            "url": c.get("url"), "views": c.get("views"), "instagram": (c.get("ig") or {}).get("url"),
            "created": time.strftime("%H:%M", time.localtime(c["created"]))}


def get_status():
    try:
        st = json.loads((ROOT / "logs" / "status.json").read_text())
        st["age_seconds"] = round(time.time() - st["t"])
        st["clipper_running"] = st["age_seconds"] < 30
    except Exception:
        st = {"clipper_running": False, "error": "no logs/status.json - start the clipper with ./start.sh"}
    try:
        with _db() as c:
            st["clips_last_24h"] = dict(c.execute("SELECT status, COUNT(*) FROM clips WHERE created>? GROUP BY status",
                                                   (time.time() - 86400,)).fetchall())
    except sqlite3.OperationalError:
        st["clips_last_24h"] = {}
    st["pending_actions"] = [a for a in load_actions() if a["state"] == "pending"]
    return st


def list_clips(status="", channel="", hours=24):
    where, a = ["created>?"], [time.time() - 3600 * int(hours or 24)]
    if status:
        where.append("status=?"); a.append(status)
    if channel:
        where.append("channel=?"); a.append(channel)
    return [_brief(c) for c in _clips(" AND ".join(where), a, 40)]


def clip_detail(clip_id):
    r = _clips("id=?", (clip_id,), 1)
    return r[0] if r else {"error": f"no clip {clip_id}"}


def campaign_stats():
    try:
        with _db() as c:
            t = c.execute("SELECT MAX(t) FROM stats").fetchone()[0]
            rows = c.execute("SELECT campaign_id, post_id, clip_id, views, likes, review, status FROM stats WHERE t=?",
                             (t,)).fetchall()
    except sqlite3.OperationalError:
        return {"error": "no stats yet (run.py --stats or wait for the 30-min tracker)"}
    return {"as_of": time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) if t else None, "rows": [dict(r) for r in rows]}


def ai_usage(hours=24):
    try:
        with _db() as c:
            rows = c.execute("SELECT tier, COUNT(*), SUM(ok), SUM(tokens_in), SUM(tokens_out) FROM ai_calls WHERE t>? "
                             "GROUP BY tier", (time.time() - int(hours or 24) * 3600,)).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {r[0]: {"calls": r[1], "ok": r[2], "tokens_in": r[3] or 0, "tokens_out": r[4] or 0} for r in rows}


def read_vault(path=""):
    p = (path or "").strip().lstrip("/")
    if not p:
        return sorted(str(f.relative_to(VAULT)) for f in VAULT.rglob("*") if f.is_file())
    f = (VAULT / p).resolve()
    if VAULT.resolve() not in f.parents or not f.is_file():
        return {"error": "not found (only files inside vault/ can be read)"}
    return f.read_text()[:12000]


def tail_log(lines=60):
    n = max(10, min(300, int(lines or 60)))
    try:
        return "\n".join((ROOT / "logs" / "clipper.log").read_text(errors="ignore").splitlines()[-n:])
    except FileNotFoundError:
        return "no log yet"


# ---------- proposals (never applied without the user's Yes) ----------
def load_actions():
    try:
        return json.loads(ACTIONS.read_text())
    except Exception:
        return []


def _save_actions(acts):
    ACTIONS.parent.mkdir(parents=True, exist_ok=True)
    tmp = ACTIONS.with_suffix(".tmp")
    tmp.write_text(json.dumps(acts[-200:], indent=1, ensure_ascii=False))
    tmp.replace(ACTIONS)


def request_action(kind, target, value="", reason=""):
    if kind not in KINDS:
        return {"error": f"kind must be one of {KINDS}"}
    acts = load_actions()
    a = {"id": uuid.uuid4().hex[:8], "t": time.time(), "kind": kind, "target": target, "value": value,
         "reason": reason, "state": "pending"}
    acts.append(a)
    _save_actions(acts)
    return {"queued": a, "note": "The user must confirm this in the dashboard (./tui.sh) or with run.py --actions."}


def describe(a):
    extra = f' -> "{a["value"]}"' if a.get("value") else ""
    return f'{a["kind"].upper()} {a["target"]}{extra}\nwhy: {a.get("reason") or "-"}'


def apply_action(a, approved):
    """Run (or decline) one queued proposal. Returns a short result string."""
    from clipper import db as cdb
    from clipper.scheduler import set_paused
    acts = load_actions()
    for x in acts:
        if x["id"] == a["id"]:
            x["state"] = "declined" if not approved else "done"
            x["decided_at"] = time.time()
    msg = "declined"
    if approved:
        k, t = a["kind"], a["target"]
        if k in ("approve", "reject"):
            c = cdb.get_clip(t)
            if not c:
                msg = f"no clip {t}"
            elif c["status"] not in ("review", "upload_failed", "auto"):
                msg = f"{t} is already {c['status']}"
            else:
                cdb.update_clip(t, status="approved" if k == "approve" else "rejected", decided_by="claude+user",
                                decided_at=time.time())
                msg = f"{t} -> {'approved' if k == 'approve' else 'rejected'}"
        elif k == "set_title":
            c = cdb.get_clip(t)
            if not c or c.get("uploaded_at"):
                msg = "unknown or already uploaded"
            else:
                new = a["value"].replace(" #GTA6 #shorts", "").strip()[:85]
                old = c.get("title", "").replace(" #GTA6 #shorts", "")
                cdb.update_clip(t, title=new + " #GTA6 #shorts", description=c.get("description", "").replace(old, new, 1))
                msg = f"{t} retitled"
        elif k in ("pause", "resume"):
            set_paused(t, k == "pause")
            msg = f"{t} {k}d"
        for x in acts:
            if x["id"] == a["id"]:
                x["result"] = msg
    _save_actions(acts)
    return msg
