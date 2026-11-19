"""Cover image for a clip: the frame a few seconds before chat peaked, taken from
the FINISHED clip, so it already carries the facecam, the hook text and the layout."""
import subprocess
from pathlib import Path


def cover(item, lead=4.0):
    ev = item.get("event") or {}
    dur = float(item.get("duration") or 20)
    start = float(item.get("trim_start") or 0)
    t = (ev.get("spike_at", 0) - ev.get("t0", 0)) - lead - start if ev else dur / 2
    t = max(1.0, min(dur - 1.0, t if t > 0 else dur / 2))
    out = Path(item["file"]).with_suffix(".cover.jpg")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t:.2f}", "-i", item["file"],
                    "-frames:v", "1", "-q:v", "2", str(out)], check=True)
    return str(out)
