#!/usr/bin/env bash
# One-time setup for the GTA 6 auto-clipper (Ubuntu).
set -e
cd "$(dirname "$0")"

if ! command -v ffmpeg >/dev/null; then
  echo "Installing ffmpeg (needs sudo)…"
  sudo apt-get update && sudo apt-get install -y ffmpeg
fi

python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install streamlink faster-whisper chat-downloader discord.py pytrends textual mcp

# Optional GPU speed-up for captions on NVIDIA (safe to fail)
pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*" || true

npm install
mkdir -p shots logs queue clips rec
chmod +x start.sh
echo
if ! command -v claude >/dev/null && [ ! -x "$HOME/.local/bin/claude" ]; then
  echo "Installing the Claude Code CLI (Claude runs on your Claude login, no API key)…"
  curl -fsSL https://claude.ai/install.sh | bash || echo "  -> install it by hand: https://code.claude.com/docs/en/setup"
fi
echo "Setup done. Next:"
echo "  0) claude          (once: log in with your Claude account, then /exit)"
echo "  1) node open-browser.js https://studio.youtube.com   (log in to @strange-cutx once; keep the window open)"
echo "  2) ./start.sh            (or ./start.sh --no-upload for a dry run)"
