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
# Usage: tools/key-video.sh in.mp4 out.mp4
#   WTP_KEY_R / WTP_KEY_M override the matte thresholds (see below)

set -euo pipefail

IN="${1:?input video}"
OUT="${2:?output video}"
KEY="${3:-0x002E5C}"        # the studio background
BRAND="0xFF6B26"

# Preserve the source pixel aspect ratio. intro.mp4 and loading.mp4 are coded
# 1920x1080 but carry a non-square SAR and display portrait; dropping it would
# squash the presenter.
read -r W H SAR < <(ffprobe -v error -select_streams v:0 \
  -show_entries stream=width,height,sample_aspect_ratio \
  -of csv=p=0 "$IN" | tr ',' ' ')
SAR="${SAR/:/\/}"
[ "$SAR" = "0/1" ] && SAR="1/1"

echo "$(basename "$IN"): ${W}x${H} sar=${SAR}, keying onto ${BRAND}"

# --- the matte --------------------------------------------------------------
# A colour-distance key (colorkey/chromakey) cannot tell the navy backdrop
# from dark blue-tinged clothing: the presenter's jeans and the loading clip's
# leather skirt came out full of orange holes at any tolerance that kept
# hair and skin. What actually separates them is saturation: the backdrop is
# fully saturated navy, denim and leather are desaturated. So the matte is
# built in the Cb/Cr plane with two conditions, and a pixel is background
# only if BOTH hold:
#   1. it is within R of the backdrop's chroma (Cb=${UB}, Cr=${VB}), and
#   2. its chroma magnitude from neutral grey exceeds M -- i.e. it is
#      genuinely saturated, not a dark garment that merely leans blue.
# Measured on frames of both clips: R=22 M=14 keeps every garment intact
# with a clean backdrop; R=28 M=10 starts to speckle the skirt.
R="${WTP_KEY_R:-22}"
M="${WTP_KEY_M:-14}"
# Backdrop chroma, measured from a corner of the source; override if a clip
# was shot against a different colour.
read -r _ UB VB < <(ffmpeg -nostdin -v error -ss 1 -i "$IN" -frames:v 1 \
  -vf "format=yuv444p,crop=24:24:8:8,scale=1:1" -f rawvideo -pix_fmt yuv444p - | od -An -tu1)
echo "backdrop chroma Cb=${UB} Cr=${VB}; matte R=${R} M=${M}"

MATTE="if(lt(sqrt(pow(cb(X,Y)-${UB},2)+pow(cr(X,Y)-${VB},2)),${R})*gt(sqrt(pow(cb(X,Y)-128,2)+pow(cr(X,Y)-128,2)),${M}),0,255)"

# Chroma is encoded with the BT.601 matrix. The kiosk uses the Pi's hardware
# H.264 decoder (a Pi 4 cannot software-decode 1080-class video smoothly), and
# that path converts with BT.601 whatever the stream is tagged: measured on
# the device, a 601 clip paints #FF6A27 against a #FF6B26 page while a 709 one
# paints #EE5D28. Software decode is exactly the opposite, which is why these
# clips must not be allowed to fall back to it -- see the lazy source handling
# in assets/js/kiosk.js.
ffmpeg -nostdin -v error -y -i "$IN" \
  -f lavfi -i "color=c=${BRAND}:s=${W}x${H}" \
  -filter_complex \
    "[0:v]format=yuv444p,split[src][m];\
     [m]geq=lum='${MATTE}':cb=128:cr=128,format=gray[mask];\
     [src]format=rgba[rgb];\
     [rgb][mask]alphamerge,despill=type=blue:mix=0.5:expand=0[fg];\
     [1:v]format=rgba[bg];\
     [bg][fg]overlay=shortest=1,scale=-2:min(ih\\,1080),\
     scale=out_color_matrix=bt601:out_range=tv,format=yuv420p,setsar=${SAR}" \
  -c:v libx264 -profile:v high -pix_fmt yuv420p -level 4.0 \
  -colorspace bt470bg -color_range tv \
  -r 30 -crf 21 -maxrate 5M -bufsize 10M \
  -an -movflags +faststart \
  "$OUT"

echo "wrote $OUT"
