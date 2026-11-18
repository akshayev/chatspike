# chatspike

**Live-stream auto-clipper driven by chat.** chatspike watches Twitch and YouTube streams as they happen. When chat explodes, it cuts the moment into a captioned 9:16 Short, posts it, and submits it to the matching [Content Rewards](https://contentrewards.com) clipping campaign. It is built for the GTA 6 launch.

> Other clippers wait for the stream to end and then let an AI scan the VOD. chatspike clips the moment within minutes, while it is still trending.

---

## How it works

```
 Twitch / YouTube live
        │  streamlink → ffmpeg segmenter (rolling 12-min buffer, 4 s .ts segments)
        │  chat → anonymous IRC / chat-downloader
        ▼
 Spike detector     10 s buckets · spike = ≥ 2.5× median of last 3 min and ≥ min_msgs
        ▼
 Cutter             22 s before → 8 s after the spike (chat reacts late)
        ▼
 Captioner          faster-whisper small.en on GPU (word timestamps)
        ▼
 Editor             1080×1920 · blurred fill · word-by-word captions · hook on top · CTA at the end
        ▼
 Scorer             chat ratio, volume, reaction mix, speech (+ optional Claude)
        ▼
 Publisher          YouTube Studio upload → Content Rewards submit (Playwright over CDP)
```

## Features

- **Real-time:** records while the streamer is live, with no waiting for the VOD.
- **No accounts for chat:** Twitch chat is read over anonymous IRC with no token.
- **GPU captions:** faster-whisper runs on CUDA and falls back to CPU automatically.
- **Campaign-aware:** each channel carries its own hashtags, CTA and Content Rewards campaign ID.
- **Rate-limited posting:** minimum gap between posts, plus hourly and daily caps, so a new channel doesn't look like spam.
- **Low footprint:** fits a 14 GB RAM / 6 GB VRAM laptop and keeps only a rolling buffer on disk.

## Requirements

- Linux (tested on Ubuntu), Python 3.12+, Node 18+, ffmpeg
- NVIDIA GPU optional (strongly recommended for captions)
- [Ollama](https://ollama.com) with `qwen2.5:3b` (used from milestone M1)

## Quick start

```bash
git clone https://github.com/<you>/chatspike.git && cd chatspike
bash setup.sh                                     # venv, streamlink, faster-whisper, CUDA libs, playwright
cp .env.example .env                              # optional keys
node open-browser.js https://studio.youtube.com &  # log in to YouTube + Content Rewards once
bash check.sh                                     # GPU, LLM, browser, who is live
./start.sh --no-upload                            # dry run: clips land in clips/
./start.sh                                        # full auto
```

| Command | What it does |
| --- | --- |
| `./start.sh lacy clix` | Watch only these channel keys |
| `./start.sh --no-upload` | Clip only and post nothing |
| `python3 run.py --publish <clip-id>` | Upload and submit one queued clip |
| `bash check.sh` | Health check: CUDA, Ollama, browser, live status, RAM and disk |
| `python3 run.py --status` | Recent clips: auto, review, rejected, uploaded, submitted |
| `python3 run.py --approve <id>` / `--reject <id>` | Decide a clip waiting for review (or use the Discord buttons) |
| `python3 run.py --submit <clip-id>` | Submit an uploaded clip to Content Rewards |

## Configuration

Everything lives in `config.json`:

- `channels[]`: `key`, `platform` (`twitch` or `youtube`), `source`, display `name`, `campaign_id`, `hashtags`, `cta`, `min_msgs`
- `detect`: bucket size, baseline window, spike ratio, pre/post seconds, cooldown, warm-up
- `edit`: layout (`blur`, `center`, `stack`), Whisper model and device, font
- `publish`: `auto_upload`, `auto_submit`, `min_score`, rate limits, visibility, CDP URL
- `storage`: buffer length, folders

## Project layout

```
clipper/        real-time pipeline (scheduler, recorder, chat, detector, captions, editor, hook, gate, db, notify, pipeline)
vault/          Obsidian vault: campaign rules, decisions, runbooks, playbook (read by Claude)
CLAUDE.md       instructions for Claude working on this repo
browser/        Playwright scripts: YouTube upload, Content Rewards submit
assets/fonts/   Anton (SIL OFL)
run.py          entry point
setup.sh  start.sh  check.sh
```

Runtime folders `rec/`, `clips/`, `queue/`, `logs/` and `shots/` are git-ignored.

## Roadmap

- [x] **M0 · MVP:** record, detect, cut, caption, render, upload, submit
- [x] **M1 · Safe autopilot:** SQLite, safety gate, Discord approval bot, 2-channel priority scheduler, RAM guard, NVENC, vault + CLAUDE.md
- [ ] **M2 · Reach:** Instagram Reels, thumbnail/cover maker, stats and earnings tracker
- [ ] **M3 · Smart picks:** trend scout, local-LLM → Gemini → Claude router, Obsidian vault + Context7 memory
- [ ] **M4 · Terminal app:** Textual dashboard with a Claude Agent SDK panel

## Responsible use

- Only clip streamers who allow it, through campaigns or with their permission. Follow each campaign's rules.
- Captions and titles are generated from the stream; no AI voices or AI visuals are added.
- Uploading through the browser uses your own logged-in session. Respect each platform's terms.

## Credits

Built on [streamlink](https://streamlink.github.io), [FFmpeg](https://ffmpeg.org), [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [Playwright](https://playwright.dev) and [Ollama](https://ollama.com). Font: Anton by Vernon Adams (SIL Open Font License).
