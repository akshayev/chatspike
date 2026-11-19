---
description: Diagnose the latest error in the clipper log and propose a fix
argument-hint: "[what looks wrong]"
---
Problem described by the user (may be empty): $ARGUMENTS

1. tail_log 200 and get_status; find the newest error or the thing described.
2. read_vault runbooks/known-failures.md: if it is a known failure, apply the documented fix.
3. Otherwise find the code path, and before changing any code that calls ffmpeg, streamlink, faster-whisper,
   Playwright or discord.py, check current docs with Context7.
4. Make the smallest fix, explain it in 3 lines, and add the failure + fix to vault/runbooks/known-failures.md.
Do not loosen the gate, and do not post, delete or change campaign membership.
