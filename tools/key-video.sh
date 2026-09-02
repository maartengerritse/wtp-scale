#!/usr/bin/env bash
# Replace a video's flat blue studio background with the brand orange.
#
# The presenter clips were shot on the Buynamics blue (#002E5C). That was
# invisible while the welcome screen was blue; on the orange screen it reads
# as a rectangle around him. This keys the blue out and composites him onto
# the brand colour so he stands directly on the page.
#
# Baked rather than shipped with an alpha channel on purpose: alpha video means
# VP9/WebM, which the Pi has no hardware decoder for. Re-run this script if the
# brand colour ever changes.
#
# Usage: tools/key-video.sh in.mp4 out.mp4 [keycolour] [similarity]

set -euo pipefail

IN="${1:?input video}"
OUT="${2:?output video}"
KEY="${3:-0x002E5C}"        # the studio background
SIM="${4:-0.10}"            # keep low: above ~0.15 it starts eating skin tones
BRAND="0xFF6B26"

# Preserve the source pixel aspect ratio. intro.mp4 and loading.mp4 are coded
# 1920x1080 but carry a non-square SAR and display portrait; dropping it would
# squash the presenter.
read -r W H SAR < <(ffprobe -v error -select_streams v:0 \
  -show_entries stream=width,height,sample_aspect_ratio \
  -of csv=p=0 "$IN" | tr ',' ' ')
SAR="${SAR/:/\/}"
[ "$SAR" = "0/1" ] && SAR="1/1"

echo "$(basename "$IN"): ${W}x${H} sar=${SAR}, keying ${KEY} at ${SIM} onto ${BRAND}"

# The colour conversion must be pinned to BT.709 limited range and tagged as
# such. Left to defaults, ffmpeg composites in one matrix and the browser
# decodes in another: #FF6B26 arrives on screen as #CB5532 and the background
# no longer matches the page.
ffmpeg -nostdin -v error -y -i "$IN" \
  -f lavfi -i "color=c=${BRAND}:s=${W}x${H}" \
  -filter_complex \
    "[0:v]despill=type=blue:mix=0.4:expand=0,colorkey=${KEY}:${SIM}:0.02[fg];\
     [1:v][fg]overlay=shortest=1,\
     scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,setsar=${SAR}" \
  -c:v libx264 -profile:v high -pix_fmt yuv420p -level 4.0 \
  -colorspace bt709 -color_primaries bt709 -color_trc bt709 -color_range tv \
  -r 30 -crf 21 -maxrate 5M -bufsize 10M \
  -an -movflags +faststart \
  "$OUT"

echo "wrote $OUT"
