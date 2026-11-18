"""Live chat readers. Each yields (epoch_seconds, user, text).
Twitch: anonymous IRC (no account, no token).
YouTube: via the optional `chat-downloader` package."""
import socket, time, re
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


def youtube_chat(url, stop):
    try:
        from chat_downloader import ChatDownloader
    except ImportError:
        L.error("pip install chat-downloader to read YouTube chat")
        return
    while not stop.is_set():
        try:
            chat = ChatDownloader().get_chat(url, message_types=["text_message"])
            L.info("youtube chat connected: %s", url)
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
        return youtube_chat(ch["source"], stop)
    raise ValueError("unsupported platform " + ch["platform"])
