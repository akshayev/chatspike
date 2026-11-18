# GTA 6 auto-clipper

Watches live streams, clips the moments chat explodes, edits them into captioned 9:16 Shorts, uploads them to YouTube (@strange-cutx) and submits them to the matching Content Rewards campaign.

```
stream ──streamlink──▶ rec/<ch>/<epoch>.ts   (rolling 12-min buffer)
chat   ──anon IRC────▶ 10 s buckets ─▶ spike = 2.5× median of last 3 min and ≥ min_msgs
spike  ──▶ cut 22 s before … 8 s after ─▶ Whisper word captions + hook title + CTA ─▶ 1080×1920 mp4
       ──▶ score (chat signals, or Claude if ANTHROPIC_API_KEY is set) ─▶ queue/<id>.json
publisher ─▶ best clip ≥ min_score, rate-limited ─▶ YouTube Studio upload ─▶ Content Rewards submit
```

## First run
```bash
./setup.sh                                   # ffmpeg, venv, streamlink, faster-whisper, chat-downloader
node open-browser.js https://studio.youtube.com   # log in to the @strange-cutx channel once, leave it open
./start.sh --no-upload                       # dry run: clips land in clips/, metadata in queue/
./start.sh                                   # full auto
./start.sh lacy clix                         # only some channels
python3 run.py --publish <clip-id>           # push one queued clip manually
```

## Channels (config.json)
| key | stream | campaign |
|---|---|---|
| lacy | twitch.tv/lacy | $12.5K LACY GTA VI Marathon pool |
| clix | twitch.tv/clix | $5K Clix GTA VI Marathon pool |
| bobby | twitch.tv/bobby_vanriper | Bobby VanRiper, $1/1K |
| tomo | youtube.com/@Tomovids/live | Tomo GTA VI, $2/1K |

## Settings to tune
- `min_msgs` per channel: big chats (Lacy, Clix) need 25+, small ones need 5–8.
- `publish.min_score`: raise it if too many weak clips are posted.
- `publish.min_gap_minutes`, `max_per_hour`, `max_per_day`: these keep a new channel from looking like spam.
- `edit.layout`: `blur` (default), `center`, or `stack`, which needs `"facecam": [x,y,w,h]` on the channel.

## Campaign rules this follows
- English captions, the streamer's name in the on-screen hook, the required hashtags, and a CTA in the last 4.5 s.
- No logos, no AI voice and no AI visuals (Reach bans AI-generated content).
- The Content Rewards submission is attempted right after upload (Reach requires it within 30 min).

## Files
- `logs/clipper.log` is the full run log.
- `queue/*.json` holds one entry per clip with its status: ready, low_score, stale, uploaded, submitted, or *_failed.
- `shots/yt-*` and `shots/cr-*` are screenshots of each upload and submit step, for debugging.
