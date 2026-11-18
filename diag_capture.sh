#!/usr/bin/env bash
# Compare capture methods for one Twitch channel. Prints media/wall ratio (1.00 = nothing dropped).
# Usage: bash diag_capture.sh [channel] [seconds]   (stop the clipper first so the test is clean)
cd "$(dirname "$0")"; . .venv/bin/activate
CH=${1:-lacy}; SEC=${2:-60}; URL="https://www.twitch.tv/$CH"
ratio() {  # dir -> media seconds / wall seconds between first and last segment
  python3 - "$1" <<'EOF'
import sys, glob, os, subprocess
fs = sorted(glob.glob(sys.argv[1] + "/*.ts"), key=lambda f: int(os.path.basename(f)[:-3]))
if len(fs) < 4: print("  too few segments", len(fs)); sys.exit()
d = lambda f: float(subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",f],capture_output=True,text=True).stdout or 0)
t = [int(os.path.basename(f)[:-3]) for f in fs]
media = sum(d(f) for f in fs[:-1]); wall = t[-1] - t[0]
print(f"  segments={len(fs)} media={media:.1f}s wall={wall}s ratio={media/wall:.2f}")
EOF
}
SEG=(-c copy -map 0:v:0 -map "0:a:0?" -f segment -segment_time 4 -reset_timestamps 1 -strftime 1)

echo "A) current: streamlink --stdout | ffmpeg segment"
rm -rf /tmp/capA && mkdir -p /tmp/capA
timeout $SEC bash -c "streamlink --stdout --loglevel warning '$URL' 1080p60,best | ffmpeg -hide_banner -loglevel error -i pipe:0 ${SEG[*]} /tmp/capA/%s.ts"
ratio /tmp/capA

echo "B) ffmpeg reads the HLS playlist directly"
rm -rf /tmp/capB && mkdir -p /tmp/capB
M3U8=$(streamlink --stream-url "$URL" 1080p60,best)
timeout $SEC ffmpeg -hide_banner -loglevel error -live_start_index -1 -i "$M3U8" "${SEG[@]}" /tmp/capB/%s.ts
ratio /tmp/capB

echo "C) streamlink with low-latency + 1 segment thread"
rm -rf /tmp/capC && mkdir -p /tmp/capC
timeout $SEC bash -c "streamlink --stdout --loglevel warning --twitch-low-latency --stream-segment-threads 1 '$URL' 1080p60,best | ffmpeg -hide_banner -loglevel error -i pipe:0 ${SEG[*]} /tmp/capC/%s.ts"
ratio /tmp/capC
rm -rf /tmp/capA /tmp/capB /tmp/capC
