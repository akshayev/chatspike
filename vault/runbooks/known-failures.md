# Known failures and fixes

| Symptom | Cause | Fix |
| --- | --- | --- |
| `libcublas.so.12 is not found` | pip CUDA libraries are not on the loader path | `clipper/gpu.py` preloads `site-packages/nvidia/*/lib/*.so*` with ctypes |
| `open() got an unexpected keyword argument 'metadata_errors'` | PyAV 19 dropped the argument faster-whisper passes | `captions._audio` decodes with ffmpeg into numpy |
| 261-byte `_raw.mp4`, or clips shorter than 30 s | segments restart their timestamps, so byte-joining breaks seeking | cut with the ffmpeg concat demuxer |
| capture health about 0.67 | `--stream-segment-threads 2` dropped about a third of Twitch segments | plain `streamlink --stdout` (measures 0.99) |
| Content Rewards submit never finds the upload | CR's YouTube lookup reports `status: unavailable, reason: quota` | `submit_cr.js` pastes the link instead |
| "This post is already submitted to this campaign" | already submitted (often by hand) | treated as success |
| `--publish` uploads but never submits | the process exited before the background submit thread ran | `--publish` now waits; `--submit ID` exists |
| file copied to the laptop "succeeds" but the old version stays | device_commit_files did not overwrite | use git (push, then `git pull`) |
| capture health 0.67-0.83 only when chat runs in the same process | streamlink's stderr pipe was read by a Python thread; busy app threads throttled it | recorder runs `streamlink | ffmpeg` as one detached shell pipeline (logs/rec-<ch>.log); Lacy back to 0.97. Clix once 0.74: watch, not yet explained |
| `FileNotFoundError: 'streamlink'` | ran `.venv/bin/python` without activating the venv | recorder resolves streamlink next to sys.executable |
| submit says failed but CR shows "Clip submitted" | success screen keeps the picker element in the DOM | detect "Clip submitted" text |
| clip deselected in CR picker | newest upload is PRE-selected (aria-pressed=true); clicking toggles it off | only click when not selected; tick the hidden checkbox with check() |
| `Cannot transfer files larger than 50Mb to a browser not co-located with the server` | NVENC final encode had no bitrate cap (-b:v 0) so clips exceeded 50 MB | final encode capped at 6M/8M max; `Publisher.fit_size` re-encodes anything over 45 MB before upload |
| capture health > 1.0 (e.g. 1.61) and `could not find sync byte` | detached recorder pipelines survived Ctrl+C, so two recorders wrote into one folder | pid files in logs/rec-*.pid; `recorder.kill_orphans()` at startup; scheduler.stop_all() on Ctrl+C / exit |
| Instagram: `element is not visible` at Share | hidden duplicate "Share" elements on the page | click the first VISIBLE match (same for Next) |
