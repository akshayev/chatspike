#!/usr/bin/env python3
"""GTA 6 auto-clipper.

  python3 run.py                 # watch every enabled channel, clip, upload, submit
  python3 run.py lacy clix       # only these channel keys
  python3 run.py --no-upload     # clip only (review clips/ and queue/ yourself)
  python3 run.py --publish ID    # upload + submit one queued clip now
"""
import sys, queue, time
from clipper.common import load_config, log, ROOT
from clipper import pipeline

L = log("main")


def main():
    cfg = load_config()
    args = sys.argv[1:]
    if "--publish" in args:
        from clipper.common import read_json
        cid = args[args.index("--publish") + 1]
        item = read_json(pipeline.QUEUE_DIR / f"{cid}.json")
        pipeline.Publisher(cfg).publish(item)
        time.sleep(1)
        return
    if "--no-upload" in args:
        cfg["publish"]["auto_upload"] = False
    keys = [a for a in args if not a.startswith("--")]
    chans = [c for c in cfg["channels"] if c["enabled"] and (not keys or c["key"] in keys)]
    if not chans:
        sys.exit("no channels selected")
    rq = queue.Queue()
    for ch in chans:
        pipeline.ChannelWatcher(ch, cfg, rq).start()
    import threading
    threading.Thread(target=pipeline.render_worker, args=(cfg, rq), daemon=True).start()
    pipeline.Publisher(cfg).start()
    L.info("watching: %s | auto_upload=%s auto_submit=%s",
           ", ".join(c["key"] for c in chans), cfg["publish"]["auto_upload"], cfg["publish"]["auto_submit"])
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        L.info("bye")


if __name__ == "__main__":
    main()
