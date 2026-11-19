#!/usr/bin/env bash
# Compare capture methods for one Twitch channel. Prints media/wall ratio (1.00 = nothing dropped).
# Usage: bash diag_capture.sh [channel] [seconds] [methods, e.g. A or ABC] [quality, e.g. 720p60]
# The first 20 s are ignored (Twitch sends a few seconds of backlog on connect, which inflates the ratio).   (stop the clipper first so the test is clean)
cd "$(dirname "$0")"; . .venv/bin/activate
CH=${1:-lacy}; SEC=${2:-60}; ONLY=${3:-ABC}; Q=${4:-1080p60,best}; URL="https://www.twitch.tv/$CH"
ratio() {  # dir -> media seconds / wall seconds between first and last segment
  python3 - "$1" <<'EOF'
import sys, glob, os, subprocess
fs = sorted(glob.glob(sys.argv[1] + "/*.ts"), key=lambda f: int(os.path.basename(f)[:-3]))
if len(fs) < 4: print("  too few segments", len(fs)); sys.exit()
d = lambda f: float(subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",f],capture_output=True,text=True).stdout or 0)
t = [int(os.path.basename(f)[:-3]) for f in fs]
keep = [i for i, x in enumerate(t) if x >= t[0] + 20]
fs = [fs[i] for i in keep]; t = [t[i] for i in keep]
if len(fs) < 4: print("  too few segments after warm-up", len(fs)); sys.exit()
media = sum(d(f) for f in fs[:-1]); wall = t[-1] - t[0]
print(f"  segments={len(fs)} media={media:.1f}s wall={wall}s ratio={media/wall:.2f}")
EOF
}
SEG=(-c copy -map 0:v:0 -map "0:a:0?" -f segment -segment_time 4 -reset_timestamps 1 -strftime 1)

[[ $ONLY == *A* ]] && { echo "[$CH] A) current: streamlink --stdout | ffmpeg segment"
rm -rf /tmp/cap-$CH-A && mkdir -p /tmp/cap-$CH-A
timeout $SEC bash -c "streamlink --stdout --loglevel warning '$URL' $Q | ffmpeg -hide_banner -loglevel error -i pipe:0 ${SEG[*]} /tmp/cap-$CH-A/%s.ts"
ratio /tmp/cap-$CH-A; }

[[ $ONLY == *B* ]] && { echo "[$CH] B) ffmpeg reads the HLS playlist directly"
rm -rf /tmp/cap-$CH-B && mkdir -p /tmp/cap-$CH-B
M3U8=$(streamlink --stream-url "$URL" $Q)
timeout $SEC ffmpeg -hide_banner -loglevel error -live_start_index -1 -i "$M3U8" "${SEG[@]}" /tmp/cap-$CH-B/%s.ts
ratio /tmp/cap-$CH-B; }

[[ $ONLY == *C* ]] && { echo "[$CH] C) streamlink with low-latency + 1 segment thread"
rm -rf /tmp/cap-$CH-C && mkdir -p /tmp/cap-$CH-C
timeout $SEC bash -c "streamlink --stdout --loglevel warning --twitch-low-latency --stream-segment-threads 1 '$URL' $Q | ffmpeg -hide_banner -loglevel error -i pipe:0 ${SEG[*]} /tmp/cap-$CH-C/%s.ts"
ratio /tmp/cap-$CH-C; }
rm -rf /tmp/cap-$CH-A /tmp/cap-$CH-B /tmp/cap-$CH-C
