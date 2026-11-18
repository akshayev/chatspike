"""Discord bot: borderline clips arrive with a video preview and Approve / Reject
buttons; failures and posts arrive as alerts. Runs in its own thread.
Needs DISCORD_BOT_TOKEN and DISCORD_CHANNEL_ID in .env; without them every call
is a no-op and review clips can be handled from the CLI instead
(python3 run.py --approve ID / --reject ID)."""
import asyncio, os, subprocess, threading, time
from pathlib import Path
from .common import log
from . import db

L = log("discord")
_loop = None
_client = None
_channel = None
_ready = threading.Event()
MAX_UPLOAD = 9.5 * 1024 * 1024   # Discord's free upload limit is 10 MB


def enabled():
    return bool(os.environ.get("DISCORD_BOT_TOKEN") and os.environ.get("DISCORD_CHANNEL_ID"))


def start():
    if not enabled():
        L.info("Discord not configured (DISCORD_BOT_TOKEN / DISCORD_CHANNEL_ID) - review via CLI")
        return
    try:
        import discord  # noqa: F401
    except ImportError:
        L.error("pip install discord.py to enable the Discord bot")
        return
    threading.Thread(target=_run, daemon=True, name="discord").start()
    _ready.wait(timeout=30)


def _run():
    global _loop, _client
    import discord
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    _client = discord.Client(intents=discord.Intents.default())

    @_client.event
    async def on_ready():
        global _channel
        _channel = _client.get_channel(int(os.environ["DISCORD_CHANNEL_ID"])) or \
            await _client.fetch_channel(int(os.environ["DISCORD_CHANNEL_ID"]))
        L.info("Discord bot online as %s in #%s", _client.user, getattr(_channel, "name", "?"))
        _ready.set()

    @_client.event
    async def on_interaction(interaction):
        cid_full = (interaction.data or {}).get("custom_id", "")
        if ":" not in cid_full:
            return
        action, cid = cid_full.split(":", 1)
        item = db.get_clip(cid)
        if not item:
            await interaction.response.send_message(f"Unknown clip {cid}", ephemeral=True)
            return
        if item["status"] != "review":
            await interaction.response.send_message(f"Already {item['status']}", ephemeral=True)
            return
        new = "approved" if action == "approve" else "rejected"
        db.update_clip(cid, status=new, decided_by=str(interaction.user), decided_at=time.time())
        L.info("%s %s via Discord (%s)", new.upper(), cid, interaction.user)
        verb = "Approved - posting next free slot" if new == "approved" else "Rejected"
        await interaction.response.edit_message(
            content=interaction.message.content + f"\n**{verb}** by {interaction.user.display_name}",
            view=None)

    _loop.run_until_complete(_client.start(os.environ["DISCORD_BOT_TOKEN"]))


def _submit(coro):
    if _loop and _ready.is_set():
        try:
            asyncio.run_coroutine_threadsafe(coro, _loop).result(timeout=120)
        except Exception as e:
            L.warning("discord send failed: %s", e)
    else:
        coro.close()


def _preview(path):
    """Discord-sized copy of a clip (480x854) when the original is over 10 MB."""
    p = Path(path)
    if p.stat().st_size <= MAX_UPLOAD:
        return p
    small = p.with_name(p.stem + "_preview.mp4")
    if not small.exists():
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(p),
                        "-vf", "scale=480:-2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "30",
                        "-c:a", "aac", "-b:a", "96k", str(small)], check=False)
    return small


def alert(text):
    if not enabled():
        return

    async def go():
        await _channel.send(text[:1900])
    _submit(go())


def review(item):
    """Post a borderline clip with Approve / Reject buttons."""
    if not enabled():
        L.info("REVIEW needed: python3 run.py --approve %s   (or --reject)", item["id"])
        return
    import discord
    reasons = "; ".join(item["gate"]["soft"]) or f"score {item.get('score')} below auto-post bar"
    text = (f"**Review:** {item['title']}\n"
            f"Channel **{item['channel']}** - score **{item.get('score')}** - {item.get('duration', 0):.0f}s\n"
            f"Why: {reasons}\n`{item['id']}`")

    async def go():
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(label="Approve", style=discord.ButtonStyle.success,
                                        custom_id=f"approve:{item['id']}"))
        view.add_item(discord.ui.Button(label="Reject", style=discord.ButtonStyle.danger,
                                        custom_id=f"reject:{item['id']}"))
        await _channel.send(text, file=discord.File(str(_preview(item["file"]))), view=view)
        view.stop()   # clicks are handled in on_interaction, which also survives restarts
    _submit(go())
