#!/usr/bin/env bash
# chatspike terminal dashboard (the clipper runs separately via ./start.sh)
cd "$(dirname "$0")"
.venv/bin/python -c "import textual" 2>/dev/null || .venv/bin/pip install -q textual claude-agent-sdk
exec .venv/bin/python -m tui.app "$@"
