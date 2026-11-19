---
description: Go through clips waiting for review and propose approve/reject for each
---
List clips with status "review". For each, call clip_detail and read the matching vault/campaigns/*.md rules
(read_vault) if you have not this session. Judge: does it break a campaign rule, is the hook strong, is the
title accurate to the transcript? One Reach strike bans the account, so when unsure, leave it in review.
For each clip give one line (id, verdict, reason), then call request_action for the ones you are confident about.
Nothing is applied until I confirm with `python3 run.py --actions` or in the dashboard.
