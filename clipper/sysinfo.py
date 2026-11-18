"""Machine checks: free RAM (from /proc/meminfo) and whether NVENC works."""
import subprocess, functools
from .common import log

L = log("sys")


def mem_available_gb():
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024 / 1024
    except OSError:
        pass
    return 99.0


@functools.lru_cache(maxsize=1)
def nvenc_ok():
    """True if ffmpeg can actually encode with h264_nvenc on this machine."""
    try:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                            "color=c=black:s=256x256:d=0.2", "-c:v", "h264_nvenc", "-f", "null", "-"],
                           capture_output=True, timeout=20)
        ok = r.returncode == 0
    except Exception:
        ok = False
    L.info("video encoder: %s", "h264_nvenc (GPU)" if ok else "libx264 (CPU)")
    return ok


def video_args(quality="final", cfg=None):
    """Encoder args. quality='cut' = high quality intermediate, 'final' = upload file."""
    use_gpu = (cfg or {}).get("edit", {}).get("encoder", "auto") != "cpu" and nvenc_ok()
    if use_gpu:
        cq = "19" if quality == "cut" else "23"
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq", "-rc", "vbr", "-cq", cq, "-b:v", "0"]
    crf = "18" if quality == "cut" else "20"
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", crf]
