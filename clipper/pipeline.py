"""Glue: channel watcher (record + chat + detect) -> render queue -> publish queue."""
import queue, threading, time, subprocess, json, uuid
from pathlib import Path
from .common import log, ROOT, write_json, read_json
from . import recorder, chat, detector, captions, hook, editor

L = log("pipe")
QUEUE_DIR = ROOT / "queue"
QUEUE_DIR.mkdir(exist_ok=True)


class ChannelWatcher(threading.Thread):
    def __init__(self, ch, cfg, render_q):
        super().__init__(daemon=True, name=ch["key"])
        self.ch, self.cfg, self.render_q = ch, cfg, render_q
        self.rec = None

    def run(self):
        while True:
            if not recorder.is_live(self.ch):
                time.sleep(60)
                continue
            L.info("[%s] LIVE - starting", self.ch["key"])
            stop = threading.Event()
            self.rec = recorder.Recorder(self.ch, self.cfg)
            self.rec.start()
            det = detector.Detector(self.ch, self.cfg, self._on_event)
            t = threading.Thread(target=self._chat_loop, args=(det, stop), daemon=True)
            t.start()
            while self.rec.alive():
                time.sleep(10)
            L.info("[%s] stream ended / recorder stopped", self.ch["key"])
            stop.set()
            self.rec.stop()
            time.sleep(30)

    def _chat_loop(self, det, stop):
        for t, user, text in chat.reader(self.ch, stop):
            det.add(t, user, text)

    def _on_event(self, ev):
        self.render_q.put((self.ch, self.rec, ev))


def render_worker(cfg, render_q):
    clips = ROOT / cfg["storage"]["clips_dir"]
    while True:
        ch, rec, ev = render_q.get()
        try:
            wait = ev["t1"] + 8 - time.time()   # let segments finish writing
            if wait > 0:
                time.sleep(wait)
            cid = time.strftime("%m%d-%H%M%S", time.localtime(ev["t0"])) + "-" + ch["key"] + "-" + uuid.uuid4().hex[:4]
            d = clips / ch["key"]
            d.mkdir(parents=True, exist_ok=True)
            raw = rec.cut(ev["t0"], ev["t1"], d / f"{cid}_raw.mp4")
            words = captions.transcribe(raw, cfg)
            dur = editor.probe_duration(raw)
            # tighten the start: skip dead air before the first spoken word (max 6s)
            start = 0.0
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
                    "file": str(final), "created": time.time(), "status": "ready",
                    "event": ev, **meta}
            write_json(QUEUE_DIR / f"{cid}.json", item)
            L.info("[%s] READY %s score=%s '%s'", ch["key"], cid, meta["score"], meta["title"])
        except Exception as e:
            L.exception("render failed: %s", e)


class Publisher(threading.Thread):
    def __init__(self, cfg):
        super().__init__(daemon=True, name="publisher")
        self.cfg = cfg
        self.p = cfg["publish"]

    def _history(self):
        items = [read_json(f) for f in QUEUE_DIR.glob("*.json")]
        return [i for i in items if i and i.get("uploaded_at")]

    def _can_post(self):
        h = sorted(i["uploaded_at"] for i in self._history())
        nowt = time.time()
        if h and nowt - h[-1] < self.p["min_gap_minutes"] * 60:
            return False
        if sum(1 for t in h if nowt - t < 3600) >= self.p["max_per_hour"]:
            return False
        if sum(1 for t in h if nowt - t < 86400) >= self.p["max_per_day"]:
            return False
        return True

    def run(self):
        while True:
            time.sleep(20)
            if not self.p["auto_upload"]:
                continue
            ready = [read_json(f) for f in QUEUE_DIR.glob("*.json")]
            ready = [i for i in ready if i and i["status"] == "ready"]
            for i in ready:   # stale or weak clips are skipped, not posted
                if time.time() - i["created"] > 90 * 60:
                    i["status"] = "stale"; write_json(QUEUE_DIR / f"{i['id']}.json", i)
                elif i["score"] < self.p["min_score"]:
                    i["status"] = "low_score"; write_json(QUEUE_DIR / f"{i['id']}.json", i)
            ready = [i for i in ready if i["status"] == "ready"]
            if not ready or not self._can_post():
                continue
            item = max(ready, key=lambda i: i["score"])
            self.publish(item)

    def publish(self, item):
        path = QUEUE_DIR / f"{item['id']}.json"
        L.info("UPLOADING %s (score %s)", item["id"], item["score"])
        item["status"] = "uploading"; write_json(path, item)
        r = subprocess.run(["node", str(ROOT / "browser" / "upload_youtube.js"), str(path)],
                           capture_output=True, text=True, timeout=900)
        out = _last_json(r.stdout)
        if not out or not out.get("videoId"):
            item["status"] = "upload_failed"; item["error"] = (r.stderr or r.stdout)[-1500:]
            write_json(path, item)
            L.error("upload failed %s: %s", item["id"], item["error"][-300:])
            return
        item.update(status="uploaded", uploaded_at=time.time(), video_id=out["videoId"], url=out["url"])
        write_json(path, item)
        L.info("UPLOADED %s -> %s", item["id"], out["url"])
        if self.p["auto_submit"]:
            threading.Thread(target=self.submit, args=(item,), daemon=True).start()

    def submit(self, item):
        path = QUEUE_DIR / f"{item['id']}.json"
        r = subprocess.run(["node", str(ROOT / "browser" / "submit_cr.js"), str(path)],
                           capture_output=True, text=True, timeout=1800)
        out = _last_json(r.stdout) or {}
        item = read_json(path)
        item["status"] = "submitted" if out.get("ok") else "submit_failed"
        item["submit_result"] = out or (r.stderr or "")[-1500:]
        write_json(path, item)
        L.info("SUBMIT %s -> %s", item["id"], item["status"])


def _last_json(s):
    for line in reversed((s or "").strip().splitlines()):
        try:
            return json.loads(line)
        except Exception:
            continue
    return None
