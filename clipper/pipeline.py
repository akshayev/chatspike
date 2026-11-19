"""Render worker (cut -> captions -> edit -> score -> gate) and Publisher
(upload -> Content Rewards submit). State lives in SQLite (clipper/db.py);
queue/<id>.json is written only as the hand-off file for the Node scripts."""
import threading, time, subprocess, json, uuid, urllib.request
from .common import log, ROOT, write_json
from . import captions, hook, editor, gate, db, notify

L = log("pipe")
QUEUE_DIR = ROOT / "queue"
QUEUE_DIR.mkdir(exist_ok=True)


def render_worker(cfg, render_q, chans_by_key):
    clips = ROOT / cfg["storage"]["clips_dir"]
    while True:
        ch, rec, ev = render_q.get()
        cid = None
        try:
            wait = ev["t1"] + 8 - time.time()   # let segments finish writing
            if wait > 0:
                time.sleep(wait)
            cid = time.strftime("%m%d-%H%M%S", time.localtime(ev["t0"])) + "-" + ch["key"] + "-" + uuid.uuid4().hex[:4]
            d = clips / ch["key"]
            d.mkdir(parents=True, exist_ok=True)
            db.log_event(ch["key"], "spike", ev)
            raw = rec.cut(ev["t0"], ev["t1"], d / f"{cid}_raw.mp4")
            words = captions.transcribe(raw, cfg)
            dur = editor.probe_duration(raw)
            start = 0.0   # skip dead air before the first spoken word (max 6s)
            if words and 2.5 < words[0]["s"] < 8:
                start = min(6.0, words[0]["s"] - 0.4)
            meta = hook.make_meta(ch, ev, words, cfg)
            ass = d / f"{cid}.ass"
            layout = ch.get("layout", cfg["edit"].get("layout", "blur"))
            ass.write_text(captions.build_ass(words, meta["hook"], ch["cta"], dur - start, cfg,
                                              offset=start, layout=layout))
            final = d / f"{cid}.mp4"
            editor.render(raw, ass, final, ch, cfg, start=start, duration=dur - start)
            raw.unlink(missing_ok=True)
            item = {"id": cid, "channel": ch["key"], "campaign_id": ch["campaign_id"],
                    "file": str(final), "created": time.time(), "duration": round(dur - start, 2),
                    "event": ev, **meta}
            item["gate"] = gate.check(item, ch, cfg)
            item["status"] = item["gate"]["decision"]
            db.save_clip(item)
            L.info("[%s] %s %s score=%s '%s'%s", ch["key"], item["status"].upper(), cid, meta["score"],
                   meta["title"], "" if item["status"] == "auto" else
                   f" | {'; '.join(item['gate']['hard'] + item['gate']['soft'])}")
            if item["status"] == "review":
                notify.review(item)
        except Exception as e:
            L.exception("render failed: %s", e)
            notify.alert(f"Render failed for {cid or ch['key']}: {e}")


class Publisher(threading.Thread):
    def __init__(self, cfg):
        super().__init__(daemon=True, name="publisher")
        self.cfg = cfg
        self.p = cfg["publish"]
        self.max_age = cfg.get("gate", {}).get("max_age_minutes", 90) * 60

    def _can_post(self):
        nowt = time.time()
        h = db.upload_times(since=nowt - 86400)
        if h and nowt - h[-1] < self.p["min_gap_minutes"] * 60:
            return False
        if sum(1 for t in h if nowt - t < 3600) >= self.p["max_per_hour"]:
            return False
        return len(h) < self.p["max_per_day"]

    def run(self):
        while True:
            time.sleep(20)
            try:
                self.tick()
            except Exception as e:
                L.exception("publisher tick failed: %s", e)

    def tick(self):
        waiting = db.clips(status=["auto", "approved", "review"])
        for i in waiting:
            if time.time() - i["created"] > self.max_age:
                db.update_clip(i["id"], status="stale")
        if not self.p["auto_upload"]:
            return
        ready = [i for i in db.clips(status=["auto", "approved"]) if time.time() - i["created"] <= self.max_age]
        if not ready or not self._can_post():
            return
        if not self.browser_ready():
            return
        # approved-by-you first, then highest score
        item = max(ready, key=lambda i: (i["status"] == "approved", i.get("score", 0)))
        self.publish(item)

    def browser_ready(self):
        """The uploader drives the logged-in clipper browser over CDP. If it is not
        running, start it and wait; never burn a clip on a closed browser."""
        url = self.p.get("cdp_url", "http://127.0.0.1:9222") + "/json/version"

        def up():
            try:
                urllib.request.urlopen(url, timeout=3).read()
                return True
            except Exception:
                return False
        if up():
            self._browser_alerted = False
            return True
        L.warning("clipper browser not reachable on %s - starting it", url)
        log_f = open(ROOT / "logs" / "browser.log", "ab")
        subprocess.Popen(["node", str(ROOT / "open-browser.js"), "https://studio.youtube.com"],
                         stdout=log_f, stderr=log_f, start_new_session=True, cwd=ROOT)
        for _ in range(20):
            time.sleep(1.5)
            if up():
                L.info("clipper browser started")
                return True
        if not getattr(self, "_browser_alerted", False):
            notify.alert("Clipper browser won't start - clips are waiting. Run: node open-browser.js")
            self._browser_alerted = True
        return False

    def _handoff(self, item):
        path = QUEUE_DIR / f"{item['id']}.json"
        write_json(path, item)
        return path

    def publish(self, item, wait=False):
        cid = item["id"]
        if not self.browser_ready():
            L.error("not uploading %s: clipper browser is not running", cid)
            return
        L.info("UPLOADING %s (score %s)", cid, item.get("score"))
        item = db.update_clip(cid, status="uploading")
        r = subprocess.run(["node", str(ROOT / "browser" / "upload_youtube.js"), str(self._handoff(item))],
                           capture_output=True, text=True, timeout=900)
        out = _last_json(r.stdout)
        if not out or not out.get("videoId"):
            err = (r.stderr or r.stdout)[-1500:]
            db.update_clip(cid, status="upload_failed", error=err)
            L.error("upload failed %s: %s", cid, err[-300:])
            notify.alert(f"YouTube upload failed for {cid}. See shots/yt-{cid}-error.png\n```{err[-400:]}```")
            return
        item = db.update_clip(cid, status="uploaded", uploaded_at=time.time(), video_id=out["videoId"], url=out["url"])
        L.info("UPLOADED %s -> %s", cid, out["url"])
        notify.alert(f"Posted **{item['title']}** (score {item.get('score')})\n{out['url']}")
        if self.p["auto_submit"]:
            if wait:
                self.submit(item)
            else:
                threading.Thread(target=self.submit, args=(item,), daemon=True).start()

    def submit(self, item):
        cid = item["id"]
        if not self.browser_ready():
            L.error("not submitting %s: clipper browser is not running", cid)
            db.update_clip(cid, status="submit_failed", submit_result="clipper browser not running")
            return
        L.info("SUBMITTING %s to campaign %s", cid, item["campaign_id"])
        r = subprocess.run(["node", str(ROOT / "browser" / "submit_cr.js"), str(self._handoff(item))],
                           capture_output=True, text=True, timeout=1800)
        out = _last_json(r.stdout) or {}
        ok = bool(out.get("ok"))
        db.update_clip(cid, status="submitted" if ok else "submit_failed",
                       submit_result=out or (r.stderr or "")[-1500:])
        L.info("SUBMIT %s -> %s %s", cid, "submitted" if ok else "submit_failed",
               "" if ok else (str(out)[:300] if out else (r.stderr or r.stdout)[-400:]))
        if not ok:
            notify.alert(f"Content Rewards submit FAILED for {cid} - submit by hand within 30 min:\n"
                         f"{item.get('url')}\n{out.get('error', '')}")


def _last_json(s):
    for line in reversed((s or "").strip().splitlines()):
        try:
            return json.loads(line)
        except Exception:
            continue
    return None
