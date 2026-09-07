#!/usr/bin/env bash
# Re-encode kiosk videos to the profile proven to play in Chromium on Raspberry Pi.
#
# Why these flags:
#   -profile:v high -pix_fmt yuv420p   8-bit H.264. Chromium CANNOT decode 10-bit
#                                      (High 10 / yuv420p10le). This is the whole point.
#   -level 4.0                         within Pi hardware decode limits at 1080p30
#   -movflags +faststart               moov atom first, so playback starts immediately
#   -an                                every video is muted; audio is dead weight
#   scale=iw*sar:ih ... setsar=1       bake the display shape into the pixels.
#                                      Chromium on the Pi ignores a non-square
#                                      pixel aspect ratio and shows the raw
#                                      frame, so a 4:5 clip stored as 1920x1080
#                                      came out as a squashed 16:9. Square
#                                      pixels look the same everywhere.
#   no padding                         aspect ratio is handled in CSS by object-fit
#
# Usage: tools/encode-videos.sh [indir] [outdir]

set -euo pipefail

IN="${1:-assets/video}"
OUT="${2:-assets/video-encoded}"
mkdir -p "$OUT"

for f in "$IN"/*.mp4; do
  name=$(basename "$f")
  echo "==> $name"
  ffmpeg -nostdin -v error -y -i "$f" \
    -c:v libx264 -profile:v high -pix_fmt yuv420p -level 4.0 \
    -vf "scale=iw*sar:ih,scale=1920:1080:force_original_aspect_ratio=decrease,setsar=1" \
    -r 30 -crf 23 -maxrate 4M -bufsize 8M \
    -an -movflags +faststart \
    "$OUT/$name"
done

echo
echo "Done. Verify with: tools/check-videos.py $OUT"
