"""chatspike terminal dashboard.   Run: ./tui.sh   (the clipper keeps running separately)

Tabs:  1 Live    channels, capture health, RAM/VRAM/disk, playbook
       2 Review  clips waiting for you: a = approve, r = reject, p = play
       3 Posted  uploads with views / Instagram / Content Rewards status
       4 Agent   chat with Claude (reads the DB/vault/log; asks before changing anything)
"""
import asyncio, json, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, RichLog, Static, TabbedContent, TabPane

from clipper.common import load_config
from clipper import db
from tui.agent import Agent


def ago(t):
    if not t:
        return "-"
    s = int(time.time() - t)
    return f"{s}s" if s < 90 else f"{s // 60}m" if s < 5400 else f"{s // 3600}h"


class Confirm(ModalScreen[bool]):
    CSS = """Confirm { align: center middle; }
    #box { width: 70; height: auto; border: thick $warning; background: $surface; padding: 1 2; }
    #btns { height: auto; margin-top: 1; }"""

    def __init__(self, text):
        super().__init__()
        self.text = text

    def compose(self) -> ComposeResult:
        with Vertical(id="box"):
            yield Label(self.text)
            with Horizontal(id="btns"):
                yield Button("Yes", variant="success", id="yes")
                yield Button("No", variant="error", id="no")

    def on_button_pressed(self, e: Button.Pressed):
        self.dismiss(e.button.id == "yes")


class Dashboard(App):
    TITLE = "chatspike"
    CSS = """#live-top { height: auto; }  #sys { padding: 0 1; }  #playbook { padding: 1; color: $text-muted; }
    DataTable { height: 1fr; }  #chat { height: 1fr; border: round $primary; }  #ask { dock: bottom; }"""
    BINDINGS = [Binding("1", "tab('live')", "Live"), Binding("2", "tab('review')", "Review"),
                Binding("3", "tab('posted')", "Posted"), Binding("4", "tab('agent')", "Agent"),
                Binding("a", "approve", "Approve"), Binding("r", "reject", "Reject"),
                Binding("p", "play", "Play clip"), Binding("q", "quit", "Quit")]

    def __init__(self):
        super().__init__()
        self.cfg = load_config()
        self.agent = Agent(self.ask_user, self.cfg.get("ai", {}).get("tui_model"))

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="live"):
            with TabPane("Live", id="live"):
                yield Static(id="sys")
                yield DataTable(id="channels", cursor_type="row")
                yield Static(id="playbook")
            with TabPane("Review", id="review"):
                yield DataTable(id="queue", cursor_type="row")
            with TabPane("Posted", id="posted"):
                yield DataTable(id="posts", cursor_type="row")
            with TabPane("Agent", id="agent"):
                yield RichLog(id="chat", wrap=True, markup=True)
                yield Input(placeholder="Ask Claude… e.g. 'what needs my review?', 'why did the last upload fail?'", id="ask")
        yield Footer()

    def on_mount(self):
        self.query_one("#channels", DataTable).add_columns("channel", "live", "recording", "since", "capture", "paused")
        self.query_one("#queue", DataTable).add_columns("clip", "ch", "score", "title", "why", "Claude says")
        self.query_one("#posts", DataTable).add_columns("time", "ch", "score", "views", "YouTube", "Instagram", "status")
        chat = self.query_one("#chat", RichLog)
        chat.write("[b]Claude operator[/b] (your Claude login via the claude CLI) - proposes changes, you confirm. /new starts over.")
        why = Agent.available()
        if why:
            chat.write(f"[yellow]{why}[/yellow]")
        self.refresh_all()
        self.set_interval(5, self.refresh_all)

    # ---------- data ----------
    def refresh_all(self):
        try:
            st = json.loads((ROOT / "logs" / "status.json").read_text())
        except Exception:
            st = {}
        fresh = st and time.time() - st.get("t", 0) < 30
        v = st.get("vram_mb") or [0, 0]
        self.query_one("#sys", Static).update(
            (f"[green]● clipper running[/green] (up {ago(st.get('started'))})" if fresh else "[red]● clipper not running[/red]  start it with ./start.sh")
            + (f"   RAM free {st.get('ram_free_gb')} GB   VRAM {v[0]}/{v[1]} MB   disk free {st.get('disk_free_gb')} GB"
               f"   upload {'on' if st.get('auto_upload') else 'OFF'}   instagram {'on' if st.get('instagram') else 'off'}"
               f"   discord {'on' if st.get('discord') else 'off'}" if st else ""))
        t = self.query_one("#channels", DataTable)
        t.clear()
        for k, c in (st.get("channels") or {}).items():
            h = c.get("health")
            ht = "-" if h is None else (f"[green]{h:.2f}[/green]" if h >= 0.9 else f"[yellow]{h:.2f}[/yellow]")
            t.add_row(k, "●" if c.get("live") else "·", "[green]REC[/green]" if c.get("recording") else "-",
                      ago(c.get("since")), ht, "[red]paused[/red]" if c.get("paused") else "")
        try:
            pb = json.loads((ROOT / "vault" / "playbook" / "current.json").read_text())
            self.query_one("#playbook", Static).update(
                f"[b]Playbook[/b] ({ago(pb.get('t'))} ago): {pb.get('summary', '')}\nHot: {', '.join(pb.get('hot_terms', [])[:8])}")
        except Exception:
            pass

        q = self.query_one("#queue", DataTable)
        keep = q.cursor_row
        q.clear()
        for c in db.clips(status="review", since=time.time() - 3 * 3600, limit=50):
            g = c.get("gate", {})
            cl = c.get("claude") or {}
            q.add_row(c["id"], c["channel"], c.get("score"), (c.get("title") or "")[:48],
                      "; ".join(g.get("soft", []) + g.get("hard", []))[:40],
                      (f"{'post' if cl.get('post') else 'skip'} {cl.get('confidence', '')}%" if cl else "-"), key=c["id"])
        if q.row_count:
            q.move_cursor(row=min(keep, q.row_count - 1))

        p = self.query_one("#posts", DataTable)
        p.clear()
        for c in db.clips(status=["uploaded", "submitted", "submit_failed"], since=time.time() - 48 * 3600, limit=80):
            ig = c.get("ig") or {}
            p.add_row(time.strftime("%d %H:%M", time.localtime(c.get("uploaded_at") or c["created"])), c["channel"],
                      c.get("score"), c.get("views", "-"), c.get("url", "-"), ig.get("url", "-"),
                      c["status"] + (f" / ig {ig.get('submit', ig.get('status', ''))}" if ig else ""), key=c["id"])

    # ---------- review actions ----------
    def _selected(self):
        q = self.query_one("#queue", DataTable)
        if not q.row_count:
            return None
        return q.coordinate_to_cell_key(q.cursor_coordinate).row_key.value

    def action_tab(self, tab):
        self.query_one(TabbedContent).active = tab

    def _decide(self, new):
        cid = self._selected()
        if not cid or self.query_one(TabbedContent).active != "review":
            return
        def done(ok):
            if ok:
                db.update_clip(cid, status=new, decided_by="tui", decided_at=time.time())
                self.notify(f"{cid} -> {new}")
                self.refresh_all()
        self.push_screen(Confirm(f"{new.upper()} {cid}?"), done)

    def action_approve(self):
        self._decide("approved")

    def action_reject(self):
        self._decide("rejected")

    def action_play(self):
        cid = self._selected()
        c = db.get_clip(cid) if cid else None
        if c and Path(c["file"]).exists():
            subprocess.Popen(["xdg-open", c["file"]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # ---------- agent ----------
    async def ask_user(self, text):
        fut = asyncio.get_running_loop().create_future()
        self.push_screen(Confirm(text), lambda ok: fut.set_result(bool(ok)) if not fut.done() else None)
        return await fut

    async def on_input_submitted(self, e: Input.Submitted):
        if e.input.id != "ask" or not e.value.strip():
            return
        chat = self.query_one("#chat", RichLog)
        chat.write(f"\n[b cyan]you>[/b cyan] {e.value}")
        e.input.value = ""
        if e.value.strip() == "/new":
            self.agent.reset(); chat.write("[dim]new conversation[/dim]"); return
        why = Agent.available()
        if why:
            chat.write(f"[yellow]{why}[/yellow]")
            return
        self.run_agent(e.value)

    @work(exclusive=True, group="agent")
    async def run_agent(self, prompt):
        chat = self.query_one("#chat", RichLog)
        try:
            await self.agent.ask(prompt, lambda t: chat.write(f"[b green]claude>[/b green] {t}"))
        except Exception as ex:
            chat.write(f"[red]agent error: {ex}[/red]")

    async def on_unmount(self):
        await self.agent.close()


if __name__ == "__main__":
    Dashboard().run()
