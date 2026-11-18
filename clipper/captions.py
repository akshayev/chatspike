"""Speech-to-text with word timings (faster-whisper, falls back to openai-whisper)
and an ASS subtitle builder: big bold words, active word highlighted, hook
title on top, CTA banner at the end."""
from .common import log

L = log("captions")
_model = None


def _load(cfg):
    global _model
    if _model is not None:
        return _model
    name = cfg["edit"]["whisper_model"]
    dev = cfg["edit"].get("whisper_device", "auto")
    try:
        from .gpu import preload_cuda
        preload_cuda()
        from faster_whisper import WhisperModel
        if dev == "auto":
            try:
                import ctranslate2
                dev = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
            except Exception:
                dev = "cpu"
        _model = ("fw", WhisperModel(name, device=dev, compute_type="float16" if dev == "cuda" else "int8"))
        L.info("faster-whisper %s on %s", name, dev)
    except ImportError:
        import whisper
        _model = ("ow", whisper.load_model(name))
        L.info("openai-whisper %s", name)
    return _model


def transcribe(path, cfg):
    """Return list of words: {w, s, e}. Falls back to CPU if the GPU path fails."""
    global _model
    try:
        return _transcribe(path, cfg)
    except RuntimeError as e:
        if "cuda" not in str(e).lower() and "cublas" not in str(e).lower() and "cudnn" not in str(e).lower():
            raise
        L.warning("GPU transcription failed (%s) - switching to CPU", e)
        cfg["edit"]["whisper_device"] = "cpu"
        _model = None
        return _transcribe(path, cfg)


def _audio(path):
    """Decode audio to 16 kHz mono float32 with ffmpeg (avoids PyAV version issues)."""
    import subprocess, numpy as np
    raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
                          "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def _transcribe(path, cfg):
    kind, m = _load(cfg)
    audio = _audio(path)
    words = []
    if kind == "fw":
        segs, _ = m.transcribe(audio, language="en", word_timestamps=True, vad_filter=True)
        for seg in segs:
            for w in seg.words or []:
                words.append({"w": w.word.strip(), "s": w.start, "e": w.end})
    else:
        r = m.transcribe(audio, language="en", word_timestamps=True)
        for seg in r["segments"]:
            for w in seg.get("words", []):
                words.append({"w": w["word"].strip(), "s": w["start"], "e": w["end"]})
    return [w for w in words if w["w"]]


def _ts(t):
    t = max(0, t)
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _esc(s):
    return s.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def _wrap(text, max_chars=18):
    out, line = [], ""
    for w in text.split():
        if len(line) + len(w) + 1 > max_chars and line:
            out.append(line)
            line = w
        else:
            line = (line + " " + w).strip()
    out.append(line)
    return "\\N".join(out[:3])


def build_ass(words, hook, cta, duration, cfg, offset=0.0):
    font = cfg["edit"].get("font", "Anton")
    per = cfg["edit"].get("caption_words_per_chunk", 3)
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},124,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,1,0,1,8,3,2,50,50,520,1
Style: Hook,{font},88,&H00FFFFFF,&H00FFFFFF,&H00000000,&HCC000000,0,0,0,0,100,100,1,0,3,18,0,8,70,70,170,1
Style: CTA,{font},70,&H00000000,&H00000000,&H0000D7FF,&H0000D7FF,0,0,0,0,100,100,1,0,3,20,0,2,80,80,330,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    if hook:
        ev.append(f"Dialogue: 1,{_ts(0)},{_ts(duration)},Hook,,0,0,0,,{{\\fad(150,0)}}{_wrap(_esc(hook.upper()), 20)}")
    if cta:
        ev.append(f"Dialogue: 1,{_ts(max(0, duration - 4.5))},{_ts(duration)},CTA,,0,0,0,,{{\\fad(200,0)}}{_esc(cta.upper())}")
    ws = [dict(w, s=w["s"] - offset, e=w["e"] - offset) for w in words]
    ws = [w for w in ws if w["e"] > 0 and w["s"] < duration]
    for i in range(0, len(ws), per):
        chunk = ws[i:i + per]
        nxt = ws[i + per]["s"] if i + per < len(ws) else duration
        for j, w in enumerate(chunk):
            s = max(0, w["s"])
            e = chunk[j + 1]["s"] if j + 1 < len(chunk) else min(w["e"] + 0.25, nxt, duration)
            if e <= s:
                continue
            parts = []
            for k, x in enumerate(chunk):
                t = _esc(x["w"].upper().strip(".,!?"))
                parts.append("{\\c&H0000E6FF&\\fscx108\\fscy108}" + t + "{\\c&H00FFFFFF&\\fscx100\\fscy100}" if k == j else t)
            ev.append(f"Dialogue: 0,{_ts(s)},{_ts(e)},Cap,,0,0,0,,{' '.join(parts)}")
    return head + "\n".join(ev) + "\n"
