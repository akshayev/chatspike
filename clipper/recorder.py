"""Records a live stream into a rolling buffer of short .ts segments named by
wall-clock epoch, so any time window can be cut later without waiting for the
stream to end. Old segments are deleted after `keep_minutes`."""
import subprocess, threading, time, json, shutil, sys, os, signal, shlex
from pathlib import Path
from .common import log, ROOT
from .sysinfo import video_args

L = log("rec")

# streamlink lives in the same venv as this Python; don't rely on PATH being activated
_venv_bin = Path(sys.executable).parent / "streamlink"
STREAMLINK = str(_venv_bin) if _venv_bin.exists() else (shutil.which("streamlink") or "streamlink")


def stream_url(ch):
    if ch["platform"] == "twitch":
        return f"https://www.twitch.tv/{ch['source']}"
    return ch["source"]


def is_live(ch):
    """Ask streamlink whether the channel has a playable stream right now."""
    try:
        out = subprocess.run(
            [STREAMLINK, "--json", stream_url(ch)],
            capture_output=True, text=True, timeout=60,
        ).stdout
        data = json.loads(out or "{}")
        return bool(data.get("streams"))
    except Exception as e:
        L.warning("live check failed for %s: %s", ch["key"], e)
        return False


class Recorder:
    def __init__(self, ch, cfg):
        self.ch, self.cfg = ch, cfg
        self.keep = cfg["storage"]["keep_minutes"] * 60
        self.dir = ROOT / cfg["storage"]["rec_dir"] / ch["key"]
        self.dir.mkdir(parents=True, exist_ok=True)
        self.sl = self.ff = None
        self.running = False

    def start(self):
        url = stream_url(self.ch)
        # Same invocation that measured 0.99 capture health in diag_capture.sh.
        # (--stream-segment-threads 2 dropped ~1/3 of Twitch segments; --twitch-disable-ads is a no-op now.)
        sl_cmd = [STREAMLINK, "--stdout", "--retry-open", "3",
                  url, self.ch.get("quality", "1080p60,1080p,best")]
        ff_cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
                  "-c", "copy", "-map", "0:v:0", "-map", "0:a:0?",
                  "-f", "segment", "-segment_time", "4", "-reset_timestamps", "1",
                  "-strftime", "1", str(self.dir / "%s.ts")]
        L.info("recording %s -> %s", url, self.dir)
        # Run streamlink | ffmpeg as ONE detached shell pipeline in its own process group,
        # with no pipes back into this Python process. When the app's threads (chat,
        # detector) were busy, the old Python-held stderr pipe throttled streamlink and
        # ~1/3 of the stream was lost (capture health 0.67 vs 1.00 detached).
        self.logf = ROOT / "logs" / f"rec-{self.ch['key']}.log"
        self._log_pos = self.logf.stat().st_size if self.logf.exists() else 0
        sl = " ".join(shlex.quote(x) for x in sl_cmd[:1] + ["--loglevel", "warning"] + sl_cmd[1:])
        ff = " ".join(shlex.quote(x) for x in ff_cmd)
        lg = shlex.quote(str(self.logf))
        self.proc = subprocess.Popen(["bash", "-c", f"{sl} 2>>{lg} | {ff} 2>>{lg}"],
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, start_new_session=True)
        self.sl = self.ff = self.proc   # kept for older callers
        self.pidfile = ROOT / "logs" / f"rec-{self.ch['key']}.pid"
        self.pidfile.write_text(str(self.proc.pid))
        self.running = True
        threading.Thread(target=self._janitor, daemon=True).start()

    def _surface_log(self):
        """Copy new streamlink/ffmpeg warnings from the recorder log into our log."""
        try:
            with open(self.logf, "rb") as f:
                f.seek(self._log_pos)
                chunk = f.read(20000)
                self._log_pos += len(chunk)
            for line in chunk.decode("utf-8", "ignore").splitlines()[-10:]:
                if line.strip() and "co located POCs" not in line:
                    L.warning("[%s] recorder: %s", self.ch["key"], line.strip()[:300])
        except OSError:
            pass

    def alive(self):
        return self.running and self.proc.poll() is None

    def stop(self):
        self.running = False
        if getattr(self, "proc", None) and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        if getattr(self, "pidfile", None):
            self.pidfile.unlink(missing_ok=True)

    def _media_len(self, f):
        try:
            out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                  "-of", "csv=p=0", str(f)], capture_output=True, text=True, timeout=10).stdout
            return float(out.strip() or 0)
        except Exception:
            return 0.0

    def health(self):
        """Media seconds captured vs wall seconds over the last ~2 minutes (1.0 = nothing dropped)."""
        segs = sorted((int(f.stem), f) for f in self.dir.glob("*.ts") if f.stem.isdigit())
        segs = [s for s in segs if s[0] > time.time() - 130][:-1]   # skip the file still being written
        if len(segs) < 5:
            return None
        wall = segs[-1][0] - segs[0][0]
        media = sum(self._media_len(f) for _, f in segs[:-1])
        return round(media / wall, 2) if wall > 0 else None

    def _janitor(self):
        last_health = time.time()
        while self.running:
            if time.time() - last_health > 120:
                last_health = time.time()
                self._surface_log()
                h = self.health()
                self.last_health = h
                if h is not None:
                    (L.warning if h < 0.9 else L.info)("[%s] capture health %.2f (media/wall, 1.00 = no drops)", self.ch["key"], h)
            cutoff = time.time() - self.keep
            for f in self.dir.glob("*.ts"):
                try:
                    if int(f.stem) < cutoff:
                        f.unlink()
                except (ValueError, FileNotFoundError):
                    pass
            time.sleep(30)

    def segments(self, t0, t1):
        """Segments overlapping wall-clock window [t0, t1], sorted."""
        segs = []
        for f in self.dir.glob("*.ts"):
            try:
                segs.append((int(f.stem), f))
            except ValueError:
                pass
        segs.sort()
        out = []
        for i, (s, f) in enumerate(segs):
            nxt = segs[i + 1][0] if i + 1 < len(segs) else s + 6
            if nxt > t0 and s < t1:
                out.append((s, f))
        return out

    def cut(self, t0, t1, dest):
        """Write wall-clock window [t0,t1] to dest (mp4, stream copy where possible)."""
        segs = self.segments(t0, t1)
        if not segs:
            raise RuntimeError("no segments for window (stream not buffered?)")
        # Each segment restarts its timestamps, so join with the concat demuxer
        # (it offsets every file correctly). Segment names are wall-clock open
        # times, so we take whole segments covering the window.
        lst = Path(dest).with_suffix(".txt")
        lst.write_text("".join(f"file '{f.resolve()}'\n" for _, f in segs))
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-t", f"{t1 - t0 + 6:.2f}",
                        *video_args("cut", self.cfg),
                        "-c:a", "aac", "-b:a", "192k", str(dest)], check=True)
        lst.unlink(missing_ok=True)
        return dest


def kill_orphans():
    """Recorder pipelines run detached, so a crash or Ctrl+C can leave them running.
    Kill any left over from a previous run (they would write duplicate segments)."""
    n = 0
    for pf in (ROOT / "logs").glob("rec-*.pid"):
        try:
            pgid = int(pf.read_text().strip())
            os.killpg(pgid, signal.SIGTERM)
            n += 1
        except (ValueError, ProcessLookupError, PermissionError):
            pass
        pf.unlink(missing_ok=True)
    if n:
        L.warning("stopped %d leftover recorder pipeline(s) from a previous run", n)
    return n
