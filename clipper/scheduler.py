"""Decides which channels record. At most `max_live` channels at once, chosen by
priority (order in config.json). A RAM guard stops new recordings when free
memory is low and drops the lowest-priority channel when it gets critical."""
import json, threading, time
from concurrent.futures import ThreadPoolExecutor
from .common import log, ROOT
from . import recorder, chat, detector, sysinfo, notify

L = log("sched")


class Session:
    """One live channel: recorder + chat reader + spike detector."""

    def __init__(self, ch, cfg, on_event):
        self.ch, self.cfg, self.on_event = ch, cfg, on_event
        self.stop_evt = threading.Event()
        self.rec = recorder.Recorder(ch, cfg)
        self.rec.start()
        self.det = detector.Detector(ch, cfg, lambda ev: on_event(ch, self.rec, ev))
        threading.Thread(target=self._chat, daemon=True, name=f"chat-{ch['key']}").start()
        self.started = time.time()

    def _chat(self):
        for t, user, text in chat.reader(self.ch, self.stop_evt):
            self.det.add(t, user, text)

    def alive(self):
        return self.rec.alive()

    def stop(self):
        self.stop_evt.set()
        self.rec.stop()


class Scheduler(threading.Thread):
    def __init__(self, chans, cfg, on_event):
        super().__init__(daemon=True, name="scheduler")
        self.chans, self.cfg, self.on_event = chans, cfg, on_event   # chans in priority order
        s = cfg.get("scheduler", {})
        self.max_live = s.get("max_live", 2)
        self.ram_pause = s.get("ram_pause_gb", 1.5)
        self.ram_critical = s.get("ram_critical_gb", 1.0)
        self.poll = s.get("poll_seconds", 60)
        self.sessions = {}            # key -> Session
        self.live = {}
        self.pool = ThreadPoolExecutor(max_workers=8)

    def _live_map(self):
        # every channel is checked each poll, recording ones too: a streamer who switches from GTA 6 to
        # Just Chatting / sleep mid-stream must stop being recorded (campaigns pay only for GTA 6)
        futs = {c["key"]: self.pool.submit(recorder.is_live, c, self.cfg) for c in self.chans}
        live = {k: f.result() for k, f in futs.items()}
        for k, s in self.sessions.items():
            off_topic = (recorder.last_meta.get(k) or {}).get("on_topic") is False
            if s.alive() and not live.get(k) and not off_topic:
                live[k] = True        # check failed / blip while recording fine: keep going
        return live

    def _stop(self, key, why):
        s = self.sessions.pop(key, None)
        if s:
            L.info("[%s] stop recording (%s)", key, why)
            s.stop()

    def tick(self):
        # clean up sessions whose stream ended
        for k in [k for k, s in self.sessions.items() if not s.alive()]:
            self._stop(k, "stream ended")
        live = self._live_map()
        self.live = live
        paused = set(control().get("paused", []))
        wanted = [c["key"] for c in self.chans if live.get(c["key"]) and c["key"] not in paused][: self.max_live]
        for k in list(self.sessions):
            if k in paused:
                self._stop(k, "paused from the dashboard")
        mem = sysinfo.mem_available_gb()

        # pre-empt lower-priority channels that are no longer in the wanted set
        for k in list(self.sessions):
            if k not in wanted:
                self._stop(k, "higher-priority channel is live")
        # critical RAM: keep only the top-priority session
        if mem < self.ram_critical and len(self.sessions) > 1:
            lowest = [c["key"] for c in self.chans if c["key"] in self.sessions][-1]
            self._stop(lowest, f"RAM critical ({mem:.1f} GB free)")
            notify.alert(f"RAM critical ({mem:.1f} GB free) - stopped recording {lowest}")
            return
        for c in self.chans:
            k = c["key"]
            if k in wanted and k not in self.sessions:
                if mem < self.ram_pause and self.sessions:
                    L.warning("[%s] live but not starting: only %.1f GB RAM free", k, mem)
                    continue
                L.info("[%s] LIVE - start recording (priority %d, %.1f GB RAM free)",
                       k, [x["key"] for x in self.chans].index(k) + 1, mem)
                self.sessions[k] = Session(c, self.cfg, self.on_event)
                mem = sysinfo.mem_available_gb()

    def run(self):
        while True:
            try:
                self.tick()
            except Exception as e:
                L.exception("scheduler tick failed: %s", e)
            time.sleep(self.poll)

    def stop_all(self):
        for k in list(self.sessions):
            self._stop(k, "shutting down")

    def status(self):
        paused = set(control().get("paused", []))
        return {c["key"]: {"live": bool(getattr(self, "live", {}).get(c["key"])),
                           "recording": c["key"] in self.sessions,
                           "since": self.sessions[c["key"]].started if c["key"] in self.sessions else None,
                           "health": getattr(self.sessions[c["key"]].rec, "last_health", None) if c["key"] in self.sessions else None,
                           "paused": c["key"] in paused,
                           "category": (recorder.last_meta.get(c["key"]) or {}).get("category"),
                           "off_topic": (recorder.last_meta.get(c["key"]) or {}).get("on_topic") is False}
                for c in self.chans}


CONTROL = ROOT / "data" / "control.json"


def control():
    try:
        return json.loads(CONTROL.read_text())
    except Exception:
        return {}


def set_paused(key, paused):
    c = control()
    p = set(c.get("paused", []))
    (p.add if paused else p.discard)(key)
    c["paused"] = sorted(p)
    CONTROL.parent.mkdir(parents=True, exist_ok=True)
    CONTROL.write_text(json.dumps(c))
