# 2026-11-19: Pool campaigns are crowded

Source: Content Rewards `GET /api/submission/pools/<id>/me` (via `python3 run.py --stats`).

- Clix pool ($5,000): **2,366 creators**. You need 400,000 counted views to qualify, then earn a share of the pool by views.
- Our first two Clix Shorts had 340 and 60 views a few hours after posting.
- Implication: pools pay only if we reach volume. CPM campaigns (Tomo $2 per 1K from 2K views, Bobby $1 per 1K from 1,950 views) pay per clip once the minimum is reached. Re-check the priority order once view data comes in (see `config.json` channels order).
