#!/usr/bin/env python3
"""Run ONLY the app's Recorder class for the given channels (no chat, no rendering,
no scheduler) and print capture health. If this shows ~1.00, the drops come from
something else in the app; if ~0.7, from the Recorder itself.
Usage: python3 diag_recorder.py lacy clix [seconds]   (stop the clipper first)"""
import shutil, sys, time
from clipper.common import load_config
from clipper import recorder

cfg = load_config()
keys = [a for a in sys.argv[1:] if not a.isdigit()] or ["lacy", "clix"]
secs = int(next((a for a in sys.argv[1:] if a.isdigit()), 180))
recs = []
for k in keys:
    ch = dict(next(c for c in cfg["channels"] if c["key"] == k), key=f"diag-{k}")
    r = recorder.Recorder(ch, cfg)
    shutil.rmtree(r.dir, ignore_errors=True); r.dir.mkdir(parents=True)
    r.start(); recs.append(r)
print(f"recording {keys} for {secs}s with the app's Recorder…")
time.sleep(secs)
for r in recs:
    print(f"  {r.ch['key']}: capture health {r.health()}  (alive={r.alive()})")
    r.stop(); shutil.rmtree(r.dir, ignore_errors=True)
