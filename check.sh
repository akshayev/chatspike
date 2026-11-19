#!/usr/bin/env bash
# Health check: GPU captions, local LLM, clipper browser, and who is live right now.
cd "$(dirname "$0")"
. .venv/bin/activate
export LD_LIBRARY_PATH="$(python3 -c 'import site,glob,os;print(":".join(sorted({os.path.dirname(p) for s in site.getsitepackages() for p in glob.glob(s+"/nvidia/*/lib/*.so*")})))'):$LD_LIBRARY_PATH"
ok(){ echo "  [OK]   $*"; }; bad(){ echo "  [FAIL] $*"; }

echo "1) Whisper on GPU (first run downloads small.en, ~500 MB)"
python3 - <<'EOF' && ok "faster-whisper runs on CUDA" || bad "faster-whisper on CUDA failed (CPU fallback). After a suspend, fix with: sudo rmmod nvidia_uvm && sudo modprobe nvidia_uvm"
import numpy as np, time, sys
sys.path.insert(0, ".")
from clipper.gpu import preload_cuda
print("     preloaded", len(preload_cuda()), "CUDA libs")
from faster_whisper import WhisperModel
t = time.time()
m = WhisperModel("small.en", device="cuda", compute_type="float16")
list(m.transcribe(np.zeros(16000 * 3, dtype=np.float32))[0])
print(f"     loaded + test transcribe in {time.time() - t:.1f}s")
EOF

echo "2) Local LLM (Ollama qwen2.5:3b)"
r=$(curl -s http://127.0.0.1:11434/api/generate -d '{"model":"qwen2.5:3b","prompt":"Reply with just OK","stream":false,"keep_alive":"10s"}' | python3 -c 'import sys,json;print(json.load(sys.stdin).get("response","").strip())' 2>/dev/null)
[ -n "$r" ] && ok "ollama replied: $r" || bad "ollama not reachable (run: ollama serve)"

echo "3) Clipper browser (CDP :9222)"
curl -s http://127.0.0.1:9222/json/version >/dev/null && ok "browser reachable" || bad "not running (run: node open-browser.js https://studio.youtube.com)"

echo "4) Who is live right now"
# every channel in config.json, in priority order (checked in parallel)
python3 - <<'PY'
import json, subprocess, concurrent.futures as cf
chs = json.load(open("config.json"))["channels"]
def url(c): return c["source"] if c["source"].startswith("http") else f"https://www.twitch.tv/{c['source']}"
import sys; sys.path.insert(0, ".")
from clipper.recorder import on_topic
def live(c):
    try:
        j = json.loads(subprocess.run(["streamlink", "--json", url(c)], capture_output=True, text=True, timeout=40).stdout or "{}")
    except Exception:
        return None
    if not j.get("streams"):
        return None
    m = j.get("metadata") or {}
    return (on_topic(c, m), m.get("category") or "?")
with cf.ThreadPoolExecutor(8) as ex:
    res = list(ex.map(live, chs))
for i, (c, on) in enumerate(zip(chs, res), 1):
    if not on:
        tag, st = "[--]  ", "offline"
    elif on[0]:
        tag, st = "[OK]  ", f"LIVE, GTA 6 ({on[1]}) - will record"
    else:
        tag, st = "[skip]", f"LIVE but not GTA 6 ({on[1]}) - skipped"
    print(f"  {tag} {i}. {c['name']:<15} {st}" + ("" if c.get("enabled", True) else "  (disabled)"))
PY

echo "5) Resources"
free -h | awk '/Mem/{print "     RAM available: "$7}'
df -h . | awk 'NR==2{print "     Disk free: "$4}'
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader | awk '{print "     VRAM used: "$0}'
