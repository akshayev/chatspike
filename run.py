#!/usr/bin/env python3
"""chatspike - live chat-spike auto-clipper.

  python3 run.py                  watch every enabled channel (max 2 live, by priority), clip, gate, post, submit
  python3 run.py lacy clix        only these channel keys (in this priority order)
  python3 run.py --no-upload      clip + gate only, post nothing
  python3 run.py --status         recent clips and what happened to them
  python3 run.py --stats          views per campaign + pool progress / estimated earnings (from Content Rewards)
  python3 run.py --trends         run the GTA 6 trend scout now and print the new hook playbook
  python3 run.py --ai-usage       AI calls per tier in the last 24 h (local / free / claude)
  python3 run.py --approve ID     approve a clip waiting for review (posts at the next free slot)
  python3 run.py --reject ID      reject a clip waiting for review
  python3 run.py --publish ID     upload + submit one clip now (ignores the gate and rate limits)
  python3 run.py --submit ID      submit an already-uploaded clip to Content Rewards
  python3 run.py --ig ID [--dry]  post one clip as an Instagram Reel (--dry stops before Share)
  python3 run.py --ig-submit ID   submit an already-posted Reel to its campaign
  python3 run.py --mark ID STATUS fix a record by hand (e.g. submitted after a manual submit)
"""
import json, queue, sys, threading, time
from clipper.common import load_config, log
from clipper import db, notify, pipeline

L = log("main")


def arg_after(args, flag):
    i = args.index(flag)
    if i + 1 >= len(args):
        sys.exit(f"{flag} needs a clip id (see --status)")
    return args[i + 1]


def status():
    rows = db.clips(since=time.time() - 24 * 3600, limit=40)
    if not rows:
        print("no clips in the last 24 h")
        return
    print(f"{'clip id':32} {'status':14} {'score':>5}  title / reason")
    for i in rows:
        why = ""
        if i["status"] in ("review", "rejected"):
            g = i.get("gate", {})
            why = " | " + "; ".join(g.get("hard", []) + g.get("soft", []))
        print(f"{i['id']:32} {i['status']:14} {i.get('score', 0):>5}  {i.get('title', '')[:60]}{why[:80]}"
              + (f"  {i['url']}" if i.get("url") else ""))


def main():
    cfg = load_config()
    args = sys.argv[1:]
    db.import_queue_dir(pipeline.QUEUE_DIR)

    if "--status" in args:
        return status()
    if "--trends" in args:
        from clipper import trends
        pb = trends.run_once(cfg)
        print(json.dumps(pb, indent=2, ensure_ascii=False) if pb else "no playbook (no AI tier answered)")
        return
    if "--ai-usage" in args:
        from clipper import ai
        print(json.dumps(ai.usage(24), indent=2))
        return
    if "--stats" in args:
        from clipper import stats
        if not pipeline.Publisher(cfg).browser_ready():
            sys.exit("clipper browser is not running")
        data = stats.fetch(cfg)
        stats.store(data)
        return stats.print_report(stats.summary(cfg, data))
    for flag, new in (("--approve", "approved"), ("--reject", "rejected")):
        if flag in args:
            cid = arg_after(args, flag)
            item = db.get_clip(cid) or sys.exit(f"unknown clip {cid}")
            db.update_clip(cid, status=new, decided_by="cli", decided_at=time.time())
            print(f"{cid}: {item['status']} -> {new}")
            return
    if "--mark" in args:   # fix a record by hand, e.g. --mark ID submitted
        i = args.index("--mark")
        cid, new = args[i + 1], args[i + 2]
        db.update_clip(cid, status=new)
        print(f"{cid}: status -> {new}")
        return
    if "--ig-submit" in args:   # resubmit an already-posted Reel to its campaign
        cid = arg_after(args, "--ig-submit")
        yt = pipeline.Publisher(cfg)
        if not yt.browser_ready():
            sys.exit("clipper browser is not running")
        pipeline.InstagramPublisher(cfg, yt).submit(cid)
        print((db.get_clip(cid).get("ig") or {}).get("submit"))
        return
    if "--ig" in args:   # --ig ID [--dry]: post one clip as a Reel (dry = stop before Share)
        cid = arg_after(args, "--ig")
        item = db.get_clip(cid) or sys.exit(f"unknown clip {cid}")
        yt = pipeline.Publisher(cfg)
        if not yt.browser_ready():
            sys.exit("clipper browser is not running")
        print(pipeline.InstagramPublisher(cfg, yt).post(item, dry="--dry" in args))
        return
    if "--publish" in args or "--submit" in args:
        flag = "--publish" if "--publish" in args else "--submit"
        cid = arg_after(args, flag)
        item = db.get_clip(cid) or sys.exit(f"unknown clip {cid} (see --status)")
        pub = pipeline.Publisher(cfg)
        pub.publish(item, wait=True) if flag == "--publish" else pub.submit(item)
        return

    if "--no-upload" in args:
        cfg["publish"]["auto_upload"] = False
    keys = [a for a in args if not a.startswith("--")]
    enabled = [c for c in cfg["channels"] if c["enabled"]]
    chans = [c for k in keys for c in enabled if c["key"] == k] if keys else enabled
    if not chans:
        sys.exit("no channels selected")

    # refuse to run twice: two copies record into the same folders and corrupt each other
    import fcntl
    from clipper.common import ROOT
    lock = open(ROOT / "logs" / "run.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit("chatspike is already running (another terminal?). Stop it first: pkill -f run.py")

    from clipper.scheduler import Scheduler
    from clipper import sysinfo
    notify.start()
    sysinfo.nvenc_ok()
    rq = queue.Queue()
    threading.Thread(target=pipeline.render_worker, args=(cfg, rq, {c["key"]: c for c in chans}),
                     daemon=True, name="render").start()
    from clipper import recorder
    recorder.kill_orphans()
    sched = Scheduler(chans, cfg, lambda ch, rec, ev: rq.put((ch, rec, ev)))
    sched.start()
    import atexit, signal as _sig
    atexit.register(sched.stop_all)
    _sig.signal(_sig.SIGTERM, lambda *a: sys.exit(0))   # run atexit on kill too
    yt = pipeline.Publisher(cfg)
    yt.start()
    pipeline.InstagramPublisher(cfg, yt).start()
    from clipper.stats import StatsTracker
    StatsTracker(cfg).start()
    from clipper.trends import TrendScout
    TrendScout(cfg).start()
    L.info("priority: %s | max live %d | auto_upload=%s | discord=%s",
           " > ".join(c["key"] for c in chans), cfg.get("scheduler", {}).get("max_live", 2),
           cfg["publish"]["auto_upload"], "on" if notify.enabled() else "off")
    notify.alert(f"chatspike started - watching {', '.join(c['key'] for c in chans)}")
    from clipper.common import ROOT, write_json
    started = time.time()
    try:
        while True:   # heartbeat for the terminal dashboard (tui/app.py)
            v = sysinfo.vram()
            write_json(ROOT / "logs" / "status.json", {
                "t": time.time(), "started": started, "pid": __import__("os").getpid(),
                "channels": sched.status(), "ram_free_gb": round(sysinfo.mem_available_gb(), 1),
                "vram_mb": v, "disk_free_gb": round(sysinfo.disk_free_gb(ROOT), 1),
                "auto_upload": cfg["publish"]["auto_upload"], "instagram": cfg["publish"].get("instagram", {}).get("enabled"),
                "discord": notify.enabled()})
            time.sleep(10)
    except KeyboardInterrupt:
        sched.stop_all()
        L.info("bye")


if __name__ == "__main__":
    main()
