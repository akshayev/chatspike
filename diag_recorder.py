#!/usr/bin/env python3
"""Run ONLY the app's Recorder class for the given channels (no chat, no rendering,
no scheduler) and print capture health. If this shows ~1.00, the drops come from
something else in the app; if ~0.7, from the Recorder itself.
Usage: .venv/bin/python diag_recorder.py lacy clix [seconds] [--chat]   (stop the clipper first)
  --chat  also run chat reading + spike detection (no rendering), like the app does"""
import shutil, sys, time
from clipper.common import load_config
from clipper import recorder, scheduler

cfg = load_config()
with_chat = "--chat" in sys.argv
keys = [a for a in sys.argv[1:] if not a.isdigit() and not a.startswith("--")] or ["lacy", "clix"]
secs = int(next((a for a in sys.argv[1:] if a.isdigit()), 180))
recs = []
for k in keys:
    ch = dict(next(c for c in cfg["channels"] if c["key"] == k), key=f"diag-{k}")
    d = recorder.Recorder(ch, cfg).dir
    shutil.rmtree(d, ignore_errors=True)
    if with_chat:   # full Session = recorder + chat reader + detector (events are dropped)
        r = scheduler.Session(dict(ch, source=ch["source"]), cfg, lambda *a: None).rec
    else:
        r = recorder.Recorder(ch, cfg); r.start()
    recs.append(r)
print(f"recording {keys} for {secs}s with the app's {'Session (recorder+chat+detector)' if with_chat else 'Recorder only'}…")
time.sleep(secs)
for r in recs:
    print(f"  {r.ch['key']}: capture health {r.health()}  (alive={r.alive()})")
    r.stop(); shutil.rmtree(r.dir, ignore_errors=True)
