"""Turns a raw 16:9 cut into a finished 9:16 Short: layout, burned captions,
hook title on top, CTA at the end, loudness normalised."""
import subprocess, json
from pathlib import Path
from .common import log, ROOT
from .sysinfo import video_args

L = log("edit")
FONTS = ROOT / "assets" / "fonts"


def probe_duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "json", str(path)], capture_output=True, text=True).stdout
    return float(json.loads(out)["format"]["duration"])


def layout_filter(mode, ch):
    if mode == "center":
        return "[0:v]scale=-2:1920,crop=1080:1920[v0]"
    if mode == "stack" and ch.get("facecam"):
        x, y, w, h = ch["facecam"]
        return (f"[0:v]scale=1920:1080,split[a][b];"
                f"[a]crop={w}:{h}:{x}:{y},scale=1080:608:force_original_aspect_ratio=increase,crop=1080:608[cam];"
                f"[b]scale=-2:1312,crop=1080:1312[game];"
                f"[cam][game]vstack[v0]")
    # blur: full frame, slightly zoomed, over a blurred fill
    return ("[0:v]split[a][b];"
            "[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,gblur=sigma=28,eq=brightness=-0.12[bg];"
            "[b]scale=1260:-2,crop=1080:ih[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2-60[v0]")


def render(raw, ass_path, out, ch, cfg, start=0.0, duration=None):
    mode = ch.get("layout", cfg["edit"].get("layout", "blur"))
    ass = str(ass_path).replace(":", r"\:")
    vf = layout_filter(mode, ch) + f";[v0]ass='{ass}':fontsdir='{FONTS}',fps=30,format=yuv420p[v]"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{start:.2f}", "-i", str(raw)]
    if duration:
        cmd += ["-t", f"{duration:.2f}"]
    cmd += ["-filter_complex", vf, "-map", "[v]", "-map", "0:a?",
            "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
            *video_args("final", cfg), "-profile:v", "high",
            "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)
    return out
