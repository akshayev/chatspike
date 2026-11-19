"""Claude operator for the dashboard, powered by the Claude Code CLI (`claude -p`).

Uses your Claude login (Pro/Max plan), so no ANTHROPIC_API_KEY is needed.
Claude gets no built-in tools (no shell, no file access) - only the chatspike MCP
server (tui/mcp_server.py): read tools plus request_action, which queues a proposal.
After each answer the dashboard asks you about every queued proposal and only then
applies it (tui/tools.apply_action).
Requires: the `claude` CLI installed and logged in, and `pip install mcp`.
"""
import asyncio, json, sys
from pathlib import Path

from tui import tools as T
from clipper.ai import claude_bin, cli_env

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ["get_status", "list_clips", "clip_detail", "campaign_stats", "ai_usage", "read_vault", "tail_log",
         "request_action"]

SYSTEM = """You are the operator assistant for chatspike, a GTA 6 live-stream auto-clipper that posts to
YouTube Shorts and Instagram Reels and submits clips to Content Rewards campaigns (LACY and Clix pools,
Tomo and Bobby per-view). Answer only from the chatspike tool results. Never state a campaign rule, number or
status from memory: read vault/campaigns/* (read_vault) or the database first, and say when something could
not be verified. One Reach strike bans the account from every Reach campaign, so be conservative with approvals.
You cannot change anything yourself: to approve, reject, retitle, pause or resume, call request_action with a
one-line reason; the user confirms it in the dashboard. Keep answers short: the user is watching a live dashboard."""


def mcp_config():
    return json.dumps({"mcpServers": {"chatspike": {"type": "stdio", "command": sys.executable,
                                                    "args": [str(ROOT / "tui" / "mcp_server.py")]}}})


class Agent:
    def __init__(self, ask_user, model=None):
        self.ask_user = ask_user          # async (text) -> bool
        self.model = model or "sonnet"
        self.session = None               # claude session id, so follow-ups keep context
        self.proc = None

    @staticmethod
    def available():
        if not claude_bin():
            return "Claude Code CLI not found. Install it (curl -fsSL https://claude.ai/install.sh | bash), run `claude` once to log in, then reopen."
        try:
            import mcp  # noqa: F401
        except ImportError:
            return "Missing python package: run  pip install mcp  (in the venv), then reopen."
        return None

    def _cmd(self, prompt):
        cmd = [claude_bin(), "-p", prompt, "--output-format", "json", "--model", self.model,
               "--tools", "",                                  # no Bash/Read/Edit/Web: MCP tools only
               "--strict-mcp-config", "--mcp-config", mcp_config(),
               "--allowedTools", ",".join(f"mcp__chatspike__{t}" for t in TOOLS),
               "--permission-mode", "dontAsk",                 # anything not allowed is denied, never prompts
               "--append-system-prompt", SYSTEM, "--max-turns", "12"]
        if self.session:
            cmd += ["--resume", self.session]
        return cmd

    async def ask(self, prompt, emit):
        before = {a["id"] for a in T.load_actions()}
        self.proc = await asyncio.create_subprocess_exec(*self._cmd(prompt), cwd=str(ROOT), env=cli_env(),
                                                         stdout=asyncio.subprocess.PIPE,
                                                         stderr=asyncio.subprocess.PIPE)
        out, err = await self.proc.communicate()
        self.proc = None
        try:
            r = json.loads(out.decode() or "{}")
        except json.JSONDecodeError:
            r = {}
        if not r:
            emit(f"[red]claude failed: {(err.decode() or out.decode())[-400:]}[/red]")
            return
        self.session = r.get("session_id") or self.session
        if r.get("is_error"):
            emit(f"[red]{r.get('result') or r.get('subtype')}[/red]  (if it says login: run `claude` once in a terminal)")
        else:
            emit(r.get("result", ""))
        # proposals made during this answer -> ask the user, one by one
        for a in [a for a in T.load_actions() if a["id"] not in before and a["state"] == "pending"]:
            ok = await self.ask_user("Claude proposes:\n\n" + T.describe(a))
            emit(f"[dim]{T.apply_action(a, ok)}[/dim]")

    def reset(self):
        self.session = None

    async def close(self):
        if self.proc and self.proc.returncode is None:
            self.proc.kill()
