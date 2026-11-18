# chatspike: instructions for Claude

Live-stream auto-clipper for the GTA 6 launch. It records Twitch and YouTube streams, cuts the moments when chat spikes, edits them into 9:16 Shorts, posts them to YouTube (@strange-cutx), and submits them to Content Rewards campaigns.

## Ground rules
- **Never state a campaign rule, number or status from memory.** Cite `vault/campaigns/*.md`, `config.json` or a row in `data/clipper.db`. If the source is missing or stale (more than 3 days since "last checked"), re-read the campaign brief before acting, and say what you could not verify.
- Before changing code that calls a library (ffmpeg, streamlink, faster-whisper, Playwright, discord.py), check current docs with Context7. Library APIs here have already broken once (see `vault/runbooks/`).
- One Reach strike bans the account from every Reach campaign. When unsure, route a clip to `review`. Never loosen the gate to post more.
- No AI voices and no AI-generated visuals in clips (Reach bans AI-generated content).
- Posting, deleting, or changing campaign membership needs the user's explicit OK.

## Layout
- `clipper/`: real-time pipeline. scheduler (priority, max 2 live, RAM guard) → recorder (streamlink | ffmpeg segments) → chat + detector (spikes) → pipeline.render_worker (cut, captions, edit, score) → gate → db → Publisher (upload, submit) → notify (Discord)
- `browser/`: Playwright scripts that attach over CDP (:9222) to the logged-in clipper browser (`open-browser.js`)
- `data/clipper.db`: SQLite source of truth (tables: clips, events, ai_calls)
- `vault/`: Obsidian vault with campaigns, decisions, runbooks, playbook and learnings
- `config.json`: channels in priority order, with thresholds and limits

## Commands
- `bash check.sh`: health check (CUDA, Ollama, browser, who is live)
- `./start.sh [--no-upload] [channels…]`: run
- `python3 run.py --status | --approve ID | --reject ID | --publish ID | --submit ID`
- `bash diag_capture.sh <channel> 60 A`: measure capture health

## Machine
Laptop: Ubuntu, i5-13450HX, 14 GB RAM (often about 5 GB free), RTX 3050 6 GB, Python 3.14 venv. The code is developed in the cloud and pushed to GitHub (akshayev/chatspike); the laptop runs `git pull`.
