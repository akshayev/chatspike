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
    # Bitrate caps keep a 60 s Short under ~45 MB: the uploader can only hand files
    # under 50 MB to the browser over CDP. 8 Mb/s is plenty for 1080x1920 @ 30 fps.
    if use_gpu:
        if quality == "cut":
            return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "19", "-b:v", "12M", "-maxrate", "16M", "-bufsize", "24M"]
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq", "-rc", "vbr", "-cq", "23",
                "-b:v", "6M", "-maxrate", "8M", "-bufsize", "12M"]
    if quality == "cut":
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-maxrate", "16M", "-bufsize", "24M"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-maxrate", "8M", "-bufsize", "12M"]


def vram():
    """(used_mb, total_mb) from nvidia-smi, or None."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5).stdout.strip().split(",")
        return int(out[0]), int(out[1])
    except Exception:
        return None


def disk_free_gb(path="."):
    import shutil
    return shutil.disk_usage(path).free / 2**30
