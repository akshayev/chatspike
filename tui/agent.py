"""Claude agent for the terminal app (Claude Agent SDK, in-process MCP tools).

The agent only acts through these tools, so every answer is grounded in the
database, the status heartbeat, the vault or the log. Tools that change
something (approve, reject, retitle, pause) ask you in the dashboard first.
Requires: pip install claude-agent-sdk, and ANTHROPIC_API_KEY in .env.
"""
import json, os, sqlite3, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "clipper.db"
VAULT = ROOT / "vault"

SYSTEM = """You are the operator assistant for chatspike, a GTA 6 live-stream auto-clipper that posts to
YouTube Shorts and Instagram Reels and submits clips to Content Rewards campaigns (LACY and Clix pools,
Tomo and Bobby per-view). Answer from tool results only. Never state a campaign rule, number or status from
memory: read vault/campaigns/* or the database first, and say when something could not be verified.
One Reach strike bans the account from every Reach campaign, so be conservative with approvals.
Before any change (approve, reject, set_title, pause, resume) explain what you will do; the dashboard asks
the user to confirm. Keep answers short: the user is watching a live dashboard."""


def _db():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def _clips(where="1=1", args=(), limit=30):
    with _db() as c:
        rows = c.execute(f"SELECT data FROM clips WHERE {where} ORDER BY created DESC LIMIT ?", (*args, limit)).fetchall()
    return [json.loads(r["data"]) for r in rows]


def _brief(c):
    g = c.get("gate", {})
    return {"id": c["id"], "channel": c["channel"], "status": c["status"], "score": c.get("score"),
            "title": c.get("title"), "hook": c.get("hook"), "duration": c.get("duration"),
            "why": (g.get("hard", []) + g.get("soft", []))[:3], "claude": c.get("claude"),
            "url": c.get("url"), "views": c.get("views"), "instagram": (c.get("ig") or {}).get("url"),
            "created": time.strftime("%H:%M", time.localtime(c["created"]))}


def _text(obj):
    return {"content": [{"type": "text", "text": obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, default=str)[:12000]}]}


def build_server(confirm):
    """confirm: async callable(text) -> bool, shown as a dialog in the dashboard."""
    from claude_agent_sdk import tool, create_sdk_mcp_server
    from clipper import db as cdb
    from clipper.scheduler import set_paused

    @tool("get_status", "Live status: channels (live/recording/health/paused), RAM, VRAM, disk, clip counts today", {})
    async def get_status(args):
        try:
            st = json.loads((ROOT / "logs" / "status.json").read_text())
            st["age_seconds"] = round(time.time() - st["t"])
        except Exception:
            st = {"error": "clipper not running (no logs/status.json)"}
        with _db() as c:
            st["clips_last_24h"] = dict(c.execute("SELECT status, COUNT(*) FROM clips WHERE created>? GROUP BY status",
                                                   (time.time() - 86400,)).fetchall())
        return _text(st)

    @tool("list_clips", "List recent clips, optionally filtered by status (review, auto, approved, uploaded, "
          "submitted, rejected, stale, upload_failed, submit_failed) and channel", {"status": str, "channel": str, "hours": int})
    async def list_clips(args):
        where, a = ["created>?"], [time.time() - 3600 * int(args.get("hours") or 24)]
        if args.get("status"):
            where.append("status=?"); a.append(args["status"])
        if args.get("channel"):
            where.append("channel=?"); a.append(args["channel"])
        return _text([_brief(c) for c in _clips(" AND ".join(where), a, 40)])

    @tool("clip_detail", "Everything recorded about one clip (transcript, chat, scores, gate, uploads)", {"id": str})
    async def clip_detail(args):
        c = cdb.get_clip(args["id"])
        return _text(c or f"no clip {args['id']}")

    async def _decide(cid, new):
        c = cdb.get_clip(cid)
        if not c:
            return _text(f"no clip {cid}")
        if c["status"] not in ("review", "upload_failed", "auto"):
            return _text(f"{cid} is '{c['status']}' - nothing to {new[:-1]}")
        if not await confirm(f"{new.upper()[:-1]} clip {cid}?\n{c.get('title')}\nscore {c.get('score')}"):
            return _text("user declined")
        cdb.update_clip(cid, status=new, decided_by="tui-agent", decided_at=time.time())
        return _text(f"{cid} -> {new}")

    @tool("approve_clip", "Approve a clip waiting for review (it posts at the next free slot). Asks the user first.", {"id": str})
    async def approve_clip(args):
        return await _decide(args["id"], "approved")

    @tool("reject_clip", "Reject a clip so it is never posted. Asks the user first.", {"id": str})
    async def reject_clip(args):
        return await _decide(args["id"], "rejected")

    @tool("set_title", "Change the title of a clip that is not uploaded yet (must contain the streamer name and "
          "'GTA 6'). Asks the user first.", {"id": str, "title": str})
    async def set_title(args):
        c = cdb.get_clip(args["id"])
        if not c or c.get("uploaded_at"):
            return _text("unknown or already uploaded")
        t = args["title"].strip()[:85]
        if not await confirm(f"Retitle {args['id']}?\nold: {c.get('title')}\nnew: {t} #GTA6 #shorts"):
            return _text("user declined")
        cdb.update_clip(args["id"], title=t + " #GTA6 #shorts",
                        description=c.get("description", "").replace(c.get("title", "").replace(" #GTA6 #shorts", ""), t, 1))
        return _text("title updated")

    @tool("pause_channel", "Stop recording a channel until resumed (e.g. off-topic stream). Asks first.", {"channel": str})
    async def pause_channel(args):
        if not await confirm(f"Pause recording {args['channel']}?"):
            return _text("user declined")
        set_paused(args["channel"], True)
        return _text(f"{args['channel']} paused (takes effect within a minute)")

    @tool("resume_channel", "Resume a paused channel. Asks first.", {"channel": str})
    async def resume_channel(args):
        if not await confirm(f"Resume recording {args['channel']}?"):
            return _text("user declined")
        set_paused(args["channel"], False)
        return _text(f"{args['channel']} resumed")

    @tool("campaign_stats", "Latest Content Rewards views per submission and per campaign (from the stats tracker)", {})
    async def campaign_stats(args):
        with _db() as c:
            try:
                t = c.execute("SELECT MAX(t) FROM stats").fetchone()[0]
                rows = c.execute("SELECT campaign_id, post_id, clip_id, views, likes, review, status FROM stats WHERE t=?",
                                 (t,)).fetchall()
            except sqlite3.OperationalError:
                return _text("no stats yet (run.py --stats or wait for the 30-min tracker)")
        return _text({"as_of": time.strftime("%H:%M", time.localtime(t)) if t else None, "rows": [dict(r) for r in rows]})

    @tool("ai_usage", "AI calls per tier (local/free/claude) in the last N hours", {"hours": int})
    async def ai_usage(args):
        from clipper import ai
        return _text(ai.usage(int(args.get("hours") or 24)))

    @tool("read_vault", "Read a vault note, e.g. campaigns/lacy-gta6-pool.md, runbooks/known-failures.md, "
          "playbook/current.json. Empty path lists the files.", {"path": str})
    async def read_vault(args):
        p = (args.get("path") or "").strip().lstrip("/")
        if not p:
            return _text(sorted(str(f.relative_to(VAULT)) for f in VAULT.rglob("*") if f.is_file()))
        f = (VAULT / p).resolve()
        if VAULT.resolve() not in f.parents or not f.exists():
            return _text("not found")
        return _text(f.read_text()[:12000])

    @tool("tail_log", "Last N lines of the clipper log (errors, uploads, decisions)", {"lines": int})
    async def tail_log(args):
        n = max(10, min(300, int(args.get("lines") or 60)))
        lines = (ROOT / "logs" / "clipper.log").read_text(errors="ignore").splitlines()[-n:]
        return _text("\n".join(lines))

    tools = [get_status, list_clips, clip_detail, approve_clip, reject_clip, set_title, pause_channel,
             resume_channel, campaign_stats, ai_usage, read_vault, tail_log]
    return create_sdk_mcp_server(name="chatspike", version="1.0.0", tools=tools), \
        [f"mcp__chatspike__{t.name}" for t in tools]


class Agent:
    def __init__(self, confirm, model=None):
        self.confirm, self.model, self.client = confirm, model, None

    @staticmethod
    def available():
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return "Add ANTHROPIC_API_KEY to .env to chat with Claude here."
        try:
            import claude_agent_sdk  # noqa: F401
        except ImportError:
            return "Install the SDK: .venv/bin/pip install claude-agent-sdk"
        return None

    async def ask(self, prompt, on_text):
        from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions, AssistantMessage, TextBlock, ResultMessage
        if self.client is None:
            server, names = build_server(self.confirm)
            opts = dict(system_prompt=SYSTEM, mcp_servers={"chatspike": server}, allowed_tools=names,
                        disallowed_tools=["Bash", "Write", "Edit", "MultiEdit", "NotebookEdit", "WebFetch", "WebSearch"],
                        max_turns=12, cwd=str(ROOT))
            if self.model:
                opts["model"] = self.model
            self.client = ClaudeSDKClient(options=ClaudeAgentOptions(**opts))
            await self.client.connect()
        await self.client.query(prompt)
        async for msg in self.client.receive_response():
            if isinstance(msg, AssistantMessage):
                for b in msg.content:
                    if isinstance(b, TextBlock) and b.text.strip():
                        on_text(b.text)
            elif isinstance(msg, ResultMessage):
                cost = getattr(msg, "total_cost_usd", None)
                if cost:
                    on_text(f"[dim](${cost:.4f})[/dim]")

    async def close(self):
        if self.client:
            await self.client.disconnect()
