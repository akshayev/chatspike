#!/usr/bin/env bash
# Starts the clipper browser (if not already running) and the auto-clipper.
cd "$(dirname "$0")"
. .venv/bin/activate
# make pip-installed CUDA libs visible to faster-whisper (no-op without NVIDIA)
export LD_LIBRARY_PATH="$(python3 -c 'import site,glob,os;print(":".join(sorted({os.path.dirname(p) for s in site.getsitepackages() for p in glob.glob(s+"/nvidia/*/lib/*.so*")})))'):$LD_LIBRARY_PATH"

if ! curl -s http://127.0.0.1:9222/json/version >/dev/null; then
  echo "Starting clipper browser…"
  nohup node open-browser.js https://studio.youtube.com >logs/browser.log 2>&1 &
  sleep 6
fi
# YouTube chat reader (pip package, installed once)
[ -x .venv/bin/yt-dlp ] || pip install -q yt-dlp
python3 run.py "$@"
