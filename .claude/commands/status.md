---
description: What is chatspike doing right now (live channels, capture health, queue, problems)
---
Call get_status, then list_clips with status "review". Report in at most 8 lines: which channels are live and
recording (with capture health), clips waiting for review, anything failing, and pending proposals.
Use only tool results. If the clipper heartbeat is stale, say so first.
