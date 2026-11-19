"""Views and earnings per campaign, read from Content Rewards every 30 minutes.

Earnings model per channel (config.json -> channels[].payout):
  {"type": "pool", "min_views": 750000}                         paid as a share of the pool if you qualify
  {"type": "cpm", "rate": 2.0, "min_views": 2000, "max": 150}   per clip: views/1000*rate if views >= min, capped
"""
import json, subprocess, threading, time
from .common import log, ROOT
from . import db, notify

L = log("stats")


def fetch(cfg):
    pools = [c["campaign_id"] for c in cfg["channels"] if c.get("payout", {}).get("type") == "pool"]
    r = subprocess.run(["node", str(ROOT / "browser" / "stats_cr.js"), json.dumps(pools)],
                       capture_output=True, text=True, timeout=180)
    for line in reversed(r.stdout.strip().splitlines()):
        try:
            data = json.loads(line)
            break
        except Exception:
            continue
    else:
        raise RuntimeError((r.stderr or r.stdout)[-400:])
    if data.get("error"):
        raise RuntimeError(data["error"])
    return data


def store(data):
    t = time.time()
    by_video = {c.get("video_id"): c for c in db.clips(limit=5000) if c.get("video_id")}
    with db._lock:
        c = db.conn()
        c.execute("""CREATE TABLE IF NOT EXISTS stats (
            t REAL, submission_id TEXT, campaign_id TEXT, post_id TEXT, clip_id TEXT,
            views INTEGER, likes INTEGER, comments INTEGER, shares INTEGER, review TEXT, status TEXT)""")
        for s in data["submissions"]:
            clip = by_video.get(s["post_id"])
            c.execute("INSERT INTO stats VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (t, s["id"], s["campaign_id"], s["post_id"], clip and clip["id"], s["views"],
                       s["likes"], s["comments"], s["shares"], s["review"], s["status"]))
        c.commit()
    for s in data["submissions"]:
        clip = by_video.get(s["post_id"])
        if clip:
            db.update_clip(clip["id"], views=s["views"], likes=s["likes"], cr_review=s["review"],
                           cr_submission_id=s["id"], stats_at=t)
    return t


def summary(cfg, data):
    """Per-campaign view totals and estimated earnings."""
    chans = {c["campaign_id"]: c for c in cfg["channels"]}
    out = []
    for cid, ch in chans.items():
        subs = [s for s in data["submissions"] if s["campaign_id"] == cid and not s["deleted"]]
        p = ch.get("payout", {})
        views = sum(s["views"] for s in subs)
        row = {"channel": ch["key"], "campaign": ch["name"], "clips": len(subs), "views": views,
               "flagged": sum(1 for s in subs if s["flagged"]),
               "rejected": sum(1 for s in subs if s["status"] == "rejected" or s["review"] == "rejected")}
        if p.get("type") == "pool":
            me = (data.get("pools") or {}).get(cid) or {}
            mine = me.get("me") or {}
            pending = int(mine.get("pendingCountedViews") or 0) + int(mine.get("countedViews") or 0)
            row.update(kind="pool", counted=pending, min_views=p["min_views"],
                       progress=f"{pending / p['min_views'] * 100:.1f}%", qualifies=bool(mine.get("qualifies")),
                       est_usd=int(mine.get("netCents") or 0) / 100, creators=me.get("creatorCount"))
        elif p.get("type") == "cpm":
            est = sum(min(p.get("max", 1e9), s["views"] / 1000 * p["rate"]) for s in subs
                      if s["views"] >= p.get("min_views", 0))
            row.update(kind="cpm", est_usd=round(est, 2), min_views=p.get("min_views"))
        out.append(row)
    return out


def print_report(rows):
    print(f"{'channel':8} {'type':5} {'clips':>5} {'views':>8}  progress / estimate")
    for r in rows:
        if r.get("kind") == "pool":
            extra = (f"{r['counted']:,} / {r['min_views']:,} counted ({r['progress']}) "
                     f"{'QUALIFIES' if r['qualifies'] else 'not yet qualified'}; {r['creators']} creators in pool")
        else:
            extra = f"~${r.get('est_usd', 0):.2f} (clips need >= {r.get('min_views')} views)"
        flags = f"  flagged {r['flagged']}" if r["flagged"] else ""
        print(f"{r['channel']:8} {r.get('kind', '?'):5} {r['clips']:>5} {r['views']:>8,}  {extra}{flags}")


class StatsTracker(threading.Thread):
    def __init__(self, cfg, every_minutes=30):
        super().__init__(daemon=True, name="stats")
        self.cfg, self.every = cfg, every_minutes * 60
        self.last_report_day = None

    def run(self):
        time.sleep(90)
        while True:
            try:
                data = fetch(self.cfg)
                store(data)
                rows = summary(self.cfg, data)
                L.info("stats: " + " | ".join(f"{r['channel']} {r['clips']} clips {r['views']:,} views" for r in rows))
                for s in data["submissions"]:
                    if s["flagged"] or s["review"] == "rejected":
                        L.warning("Content Rewards flagged/rejected %s (%s)", s["url"], s["campaign"])
                day = time.strftime("%Y-%m-%d")
                if self.last_report_day != day and time.localtime().tm_hour >= 21:
                    self.last_report_day = day
                    notify.alert("**Daily stats**\n" + "\n".join(
                        f"{r['channel']}: {r['clips']} clips, {r['views']:,} views"
                        + (f", pool {r['progress']} of {r['min_views']:,}" if r.get('kind') == 'pool'
                           else f", ~${r.get('est_usd', 0):.2f}") for r in rows))
            except Exception as e:
                L.warning("stats fetch failed: %s", e)
            time.sleep(self.every)
