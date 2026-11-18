"""Chat-spike detector.
Counts messages in N-second buckets. A bucket is a spike when it has
>= spike_ratio x the median of the previous baseline window AND >= min_msgs.
Consecutive spike buckets merge into one event. Chat reacts AFTER the moment,
so the clip window starts pre_sec before the spike."""
import math, re, statistics, threading, time
from collections import deque, Counter
from .common import log

L = log("detect")

LAUGH = re.compile(r"(lmao|lmfao|lol|kekw|omegalul|lul|icant|💀|😂|🤣|haha|xd|kek|dead)", re.I)
SHOCK = re.compile(r"(no way|what|wtf|\?\?|nahh|omg|bro|holy|😳|😱|monkas|pogo|actually)", re.I)
HYPE = re.compile(r"(\bw\b|pog|poggers|letsgo|let's go|goat|insane|clean|clip it|clip that|\bclip\b|🔥)", re.I)


class Detector:
    def __init__(self, ch, cfg, on_event):
        d = cfg["detect"]
        self.ch = ch
        self.bucket = d["bucket_sec"]
        self.base_n = max(3, d["baseline_sec"] // self.bucket)
        self.ratio = d["spike_ratio"]
        self.pre, self.post = d["pre_sec"], d["post_sec"]
        self.cooldown = d["cooldown_sec"]
        self.warmup = d["warmup_sec"]
        self.min_msgs = ch.get("min_msgs", 10)
        self.on_event = on_event
        self.started = time.time()
        self.cur_start = math.floor(time.time() / self.bucket) * self.bucket
        self.cur = []                       # (t, user, text) in current bucket
        self.history = deque(maxlen=self.base_n)
        self.recent = deque(maxlen=4000)    # all msgs, for context
        self.event = None
        self.last_event_end = 0
        self.lock = threading.Lock()
        threading.Thread(target=self._ticker, daemon=True).start()

    def add(self, t, user, text):
        with self.lock:
            self.cur.append((t, user, text))
            self.recent.append((t, user, text))

    def _ticker(self):
        while True:
            time.sleep(0.5)
            with self.lock:
                if time.time() >= self.cur_start + self.bucket:
                    self._close_bucket()

    def _close_bucket(self):
        msgs, start = self.cur, self.cur_start
        self.cur, self.cur_start = [], start + self.bucket
        n = len(msgs)
        base = statistics.median(self.history) if self.history else 0
        base = max(base, 1)
        warm = time.time() - self.started > self.warmup
        spike = warm and n >= self.min_msgs and n >= self.ratio * base and start > self.last_event_end + self.cooldown
        if spike:
            if self.event is None:
                self.event = {"start": start, "peak": n, "peak_t": start, "base": base, "msgs": [], "buckets": 0}
                L.info("[%s] spike: %d msgs vs median %.1f", self.ch["key"], n, base)
            ev = self.event
            ev["buckets"] += 1
            ev["msgs"] += msgs
            if n > ev["peak"]:
                ev["peak"], ev["peak_t"] = n, start
            if ev["buckets"] >= 3:
                self._emit()
        else:
            if self.event is not None:
                self._emit()
            # don't let spikes inflate the baseline
            self.history.append(n)

    def _emit(self):
        ev, self.event = self.event, None
        msgs = ev["msgs"]
        texts = [m[2] for m in msgs]
        laugh = sum(bool(LAUGH.search(t)) for t in texts)
        shock = sum(bool(SHOCK.search(t)) for t in texts)
        hype = sum(bool(HYPE.search(t)) for t in texts)
        total = max(1, len(texts))
        mood = max([("laugh", laugh), ("shock", shock), ("hype", hype)], key=lambda x: x[1])[0]
        t0 = ev["start"] - self.pre
        t1 = ev["start"] + self.bucket * min(ev["buckets"], 2) + self.post
        self.last_event_end = t1
        top = Counter(t.strip().lower() for t in texts).most_common(12)
        event = {
            "channel": self.ch["key"],
            "t0": t0, "t1": t1,
            "spike_at": ev["start"],
            "peak_msgs": ev["peak"], "baseline": ev["base"],
            "ratio": round(ev["peak"] / ev["base"], 2),
            "unique_chatters": len({m[1] for m in msgs}),
            "react_frac": round((laugh + shock + hype) / total, 2),
            "mood": mood,
            "top_messages": [m for m, _ in top],
            "min_msgs": self.min_msgs,
        }
        L.info("[%s] event %s ratio=%.1f mood=%s", self.ch["key"],
               time.strftime("%H:%M:%S", time.localtime(t0)), event["ratio"], mood)
        self.on_event(event)
