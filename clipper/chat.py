"""Live chat readers. Each yields (epoch_seconds, user, text).
Twitch: anonymous IRC (no account, no token).
YouTube: via the optional `chat-downloader` package."""
import json, re, shutil, socket, subprocess, sys, time
from .common import log

L = log("chat")


def twitch_chat(channel, stop):
    while not stop.is_set():
        try:
            s = socket.create_connection(("irc.chat.twitch.tv", 6667), timeout=300)
            s.sendall(b"PASS SCHMOOPIIE\r\nNICK justinfan%d\r\n" % (int(time.time()) % 90000 + 10000))
            s.sendall(f"JOIN #{channel.lower()}\r\n".encode())
            L.info("twitch chat connected: #%s", channel)
            buf = b""
            while not stop.is_set():
                data = s.recv(65536)
                if not data:
                    raise ConnectionError("closed")
                buf += data
                *lines, buf = buf.split(b"\r\n")
                for raw in lines:
                    line = raw.decode("utf-8", "ignore")
                    if line.startswith("PING"):
                        s.sendall(b"PONG :tmi.twitch.tv\r\n")
                        continue
                    m = re.match(r":(\w+)!\S+ PRIVMSG #\S+ :(.*)", line)
                    if m:
                        yield time.time(), m.group(1), m.group(2)
        except Exception as e:
            if stop.is_set():
                return
            L.warning("twitch chat #%s dropped (%s), reconnecting", channel, e)
            time.sleep(5)


def _youtube_watch_url(url):
    """chat-downloader can't resolve some handle /live URLs (e.g. @dylan.page./live: 'no videos of the
    requested type'). streamlink can, and its metadata id is the live video id -> use watch?v=ID."""
    if "watch?v=" in url:
        return url
    from . import recorder
    try:
        out = subprocess.run([recorder.STREAMLINK, "--json", url], capture_output=True, text=True, timeout=60).stdout
        vid = (json.loads(out or "{}").get("metadata") or {}).get("id")
        if vid:
            return f"https://www.youtube.com/watch?v={vid}"
    except Exception as e:
        L.warning("could not resolve live video id for %s: %s", url, e)
    return url


def _find_text_msgs(o):
    """Yield every liveChatTextMessageRenderer inside one yt-dlp live_chat JSON line (live or replay shape)."""
    if isinstance(o, dict):
        for k, v in o.items():
            if k == "liveChatTextMessageRenderer":
                yield v
            else:
                yield from _find_text_msgs(v)
    elif isinstance(o, list):
        for v in o:
            yield from _find_text_msgs(v)


def youtube_chat_ytdlp(url, stop, key="yt"):
    """YouTube live chat through yt-dlp (maintained), which writes the chat as JSON lines until the stream ends.
    chat-downloader broke on YouTube (2026-11-19: 'Unable to parse initial video data').
    Note: on live streams yt-dlp gets 'Top chat' (a filtered subset), so set min_msgs lower for YouTube channels."""
    from pathlib import Path
    from .common import ROOT
    exe = Path(sys.executable).parent / "yt-dlp"
    exe = str(exe) if exe.exists() else (shutil.which("yt-dlp") or "yt-dlp")
    out_dir = ROOT / "logs" / "chat"
    out_dir.mkdir(parents=True, exist_ok=True)
    while not stop.is_set():
        target = _youtube_watch_url(url)
        f = out_dir / f"{key}.live_chat.json"
        f.unlink(missing_ok=True)
        p = subprocess.Popen([exe, "--skip-download", "--write-subs", "--sub-langs", "live_chat", "--no-part",
                              "--quiet", "--no-warnings", "-o", str(out_dir / key), target],
                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        L.info("youtube chat (yt-dlp) started: %s", target)
        try:
            pos, buf, got = 0, "", 0
            while not stop.is_set() and p.poll() is None:
                if f.exists():
                    with open(f, encoding="utf-8", errors="ignore") as fh:
                        fh.seek(pos)
                        buf += fh.read()
                        pos = fh.tell()
                    *lines, buf = buf.split("\n")
                    now = time.time()
                    for line in lines:
                        try:
                            o = json.loads(line)
                        except ValueError:
                            continue
                        for m in _find_text_msgs(o):
                            got += 1
                            if got == 1:
                                L.info("youtube chat receiving messages (%s)", key)
                            text = "".join(r.get("text", "") for r in (m.get("message") or {}).get("runs", []))
                            yield now, (m.get("authorName") or {}).get("simpleText", "?"), text
                time.sleep(1)
            if p.poll() is not None and not stop.is_set():
                err = (p.stderr.read() or "").strip().splitlines()[-1:] if p.stderr else []
                L.warning("youtube chat (yt-dlp) ended (%s), retrying", err[0][:160] if err else f"exit {p.returncode}")
        finally:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(10)
                except subprocess.TimeoutExpired:
                    p.kill()
        if not stop.is_set():
            time.sleep(15)


def youtube_chat(url, stop):
    try:
        from chat_downloader import ChatDownloader
    except ImportError:
        L.error("pip install chat-downloader to read YouTube chat")
        return
    while not stop.is_set():
        try:
            target = _youtube_watch_url(url)      # re-resolved each retry: the live video id can change
            chat = ChatDownloader().get_chat(target, message_types=["text_message"])
            L.info("youtube chat connected: %s", target)
            for msg in chat:
                if stop.is_set():
                    return
                yield time.time(), msg.get("author", {}).get("name", "?"), msg.get("message", "")
        except Exception as e:
            L.warning("youtube chat dropped (%s), retrying", e)
            time.sleep(15)


def reader(ch, stop):
    if ch["platform"] == "twitch":
        return twitch_chat(ch["source"], stop)
    if ch["platform"] == "youtube":
        if ch.get("chat_backend", "yt-dlp") == "yt-dlp":
            return youtube_chat_ytdlp(ch["source"], stop, ch["key"])
        return youtube_chat(ch["source"], stop)
    raise ValueError("unsupported platform " + ch["platform"])
