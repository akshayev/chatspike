"""chatspike MCP server (stdio) for Claude Code.

Registered in .mcp.json for interactive `claude` sessions in this folder, and
passed with --mcp-config to the dashboard's headless agent. Read tools only,
plus request_action, which queues a proposal for the user to confirm."""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:                                                   # mcp 2.x (FastMCP renamed to MCPServer)
    from mcp.server.mcpserver import MCPServer as Server
except ImportError:                                    # mcp 1.x
    from mcp.server.fastmcp import FastMCP as Server
from tui import tools as T

mcp = Server("chatspike")
j = lambda x: x if isinstance(x, str) else json.dumps(x, ensure_ascii=False, default=str)[:15000]


@mcp.tool()
def get_status() -> str:
    """Live status: clipper running?, channels (live/recording/capture health/paused), RAM, VRAM, disk,
    clip counts in the last 24 h, and proposals waiting for the user."""
    return j(T.get_status())


@mcp.tool()
def list_clips(status: str = "", channel: str = "", hours: int = 24) -> str:
    """Recent clips. status: review, auto, approved, uploaded, submitted, rejected, stale, upload_failed,
    submit_failed (empty = all). channel: lacy, clix, tomo, bobby (empty = all)."""
    return j(T.list_clips(status, channel, hours))


@mcp.tool()
def clip_detail(clip_id: str) -> str:
    """Everything recorded about one clip: transcript, chat reaction, scores, gate result, uploads, errors."""
    return j(T.clip_detail(clip_id))


@mcp.tool()
def campaign_stats() -> str:
    """Latest Content Rewards views/likes/review status per submission (from the 30-min stats tracker)."""
    return j(T.campaign_stats())


@mcp.tool()
def ai_usage(hours: int = 24) -> str:
    """AI calls per tier (local / free / claude) in the last N hours."""
    return j(T.ai_usage(hours))


@mcp.tool()
def read_vault(path: str = "") -> str:
    """Read a vault note (campaign rules, runbooks, decisions, learnings, playbook). Empty path lists files.
    Examples: campaigns/lacy-gta6-pool.md, runbooks/known-failures.md, playbook/current.json"""
    return j(T.read_vault(path))


@mcp.tool()
def tail_log(lines: int = 60) -> str:
    """Last N lines of the clipper log (spikes, gate decisions, uploads, errors)."""
    return j(T.tail_log(lines))


@mcp.tool()
def request_action(kind: str, target: str, value: str = "", reason: str = "") -> str:
    """Propose a change for the USER to confirm (nothing happens until they say yes).
    kind: approve | reject (target = clip id), set_title (target = clip id, value = new title containing the
    streamer name and 'GTA 6'), pause | resume (target = channel key). Always give a one-line reason."""
    return j(T.request_action(kind, target, value, reason))


if __name__ == "__main__":
    mcp.run(transport="stdio")
