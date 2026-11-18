#!/usr/bin/env bash
# Health check: GPU captions, local LLM, clipper browser, and who is live right now.
cd "$(dirname "$0")"
. .venv/bin/activate
export LD_LIBRARY_PATH="$(python3 -c 'import site,glob,os;print(":".join(sorted({os.path.dirname(p) for s in site.getsitepackages() for p in glob.glob(s+"/nvidia/*/lib/*.so*")})))'):$LD_LIBRARY_PATH"
ok(){ echo "  [OK]   $*"; }; bad(){ echo "  [FAIL] $*"; }

echo "1) Whisper on GPU (first run downloads small.en, ~500 MB)"
python3 - <<'EOF' && ok "faster-whisper runs on CUDA" || bad "faster-whisper on CUDA failed (will fall back to CPU)"
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
for ch in lacy clix bobby_vanriper; do
  if streamlink --json "https://www.twitch.tv/$ch" 2>/dev/null | grep -q '"streams"'; then ok "twitch.tv/$ch is LIVE"; else echo "  [--]   twitch.tv/$ch offline"; fi
done
if streamlink --json "https://www.youtube.com/@Tomovids/live" 2>/dev/null | grep -q '"streams"'; then ok "Tomo (YouTube) is LIVE"; else echo "  [--]   Tomo (YouTube) offline"; fi

echo "5) Resources"
free -h | awk '/Mem/{print "     RAM available: "$7}'
df -h . | awk 'NR==2{print "     Disk free: "$4}'
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader | awk '{print "     VRAM used: "$0}'
