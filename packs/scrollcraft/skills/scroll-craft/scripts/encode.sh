#!/usr/bin/env bash
# scrollcraft: encode a clip for scrubbing, not for playback.
#
# A normal web encode puts a keyframe every 2-5 seconds. Scrubbing seeks to an
# arbitrary time, and the decoder must walk from the previous keyframe to get
# there, so a sparse-GOP file feels like mud under the wheel while playing back
# perfectly. Dense keyframes cost file size and buy responsiveness. That trade
# is the entire point of this script.
#
#   ./encode.sh in.mp4 out.mp4            desktop master  (1080p, -g 8, crf 20)
#   ./encode.sh in.mp4 out-m.mp4 mobile   phone variant   (short side 720, landscape or portrait, -g 4, crf 24)
#   ./encode.sh in.mp4 out-m.mp4 portrait phone variant of a LANDSCAPE clip: the centre 9:16, 720 wide, in one
#                                          pass. A clip already 9:16 or taller is not cropped, only scaled.
#
# CRF override, for the grain-heavy worlds assets.md warns about (marine snow,
# bioluminescence, smoke, film grain). A dense GOP doubles the cost of grain, so
# a world like that wants 22-23 rather than the default 20:
#
#   ./encode.sh in.mp4 out.mp4 desktop 23        fourth positional argument
#   SCROLLCRAFT_CRF=23 ./encode.sh in.mp4 out.mp4    or the env var
#
# The positional argument wins over the env var; with neither, the defaults
# below are unchanged.
#
# Audio is stripped: these clips are scrubbed, never played, and a muted track
# is dead weight plus an autoplay-policy hazard.
set -euo pipefail

# Resolve a FULL ffmpeg build. Several toolchains (Remotion, some Electron apps)
# put a stripped ffmpeg on PATH that carries maybe 50 filters and silently lacks
# scale/fps/tile. It fails with "No option name near ..." on any filter chain,
# which reads like a syntax error in your command rather than a missing filter.
# Count the filters and go looking for a real build if the count is low.
pick_ffmpeg() {
  local cand
  for cand in \
    "${SCROLLCRAFT_FFMPEG:-}" \
    "$(command -v ffmpeg 2>/dev/null || true)" \
    "${HOME:-/nonexistent}"/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_*/ffmpeg-*-full_build/bin/ffmpeg.exe \
    /usr/local/bin/ffmpeg /opt/homebrew/bin/ffmpeg /usr/bin/ffmpeg /snap/bin/ffmpeg
  do
    [ -n "$cand" ] && [ -x "$cand" ] || continue
    if [ "$("$cand" -hide_banner -filters 2>/dev/null | wc -l)" -gt 200 ]; then
      echo "$cand"; return 0
    fi
  done
  echo "ERROR: no full ffmpeg build found. Set SCROLLCRAFT_FFMPEG to one." >&2
  return 1
}
FFMPEG="$(pick_ffmpeg)"
FFPROBE="$(dirname "$FFMPEG")/ffprobe"
# ffprobe only prints the final duration line, so a missing one is a note, never a silent exit (set -e).
[ -x "$FFPROBE" ] || FFPROBE="$(command -v ffprobe || true)"

IN="${1:?usage: encode.sh <in> <out> [desktop|mobile|portrait] [crf]}"
OUT="${2:?usage: encode.sh <in> <out> [desktop|mobile|portrait] [crf]}"
MODE="${3:-desktop}"

# mobile makes the SHORT side 720, so a landscape clip comes out 720 high and a native 9:16 portrait clip
# (assets.md "Portrait") 720 wide (it used to fix the height, turning a portrait clip into 405x720).
case "$MODE" in
  mobile)  SCALE="scale='if(gt(iw,ih),-2,720)':'if(gt(iw,ih),720,-2)'"; GOP=4; CRF=24 ;;
  # a phone shows only the middle of a wide frame: cut that middle (at most 9:16, never wider than the source) and
  # encode it at 720 wide, rather than encoding the whole frame for a phone to throw most of it away
  portrait) SCALE="crop='min(iw,trunc(ih*9/16/2)*2)':ih,scale=720:-2"; GOP=4; CRF=24 ;;
  desktop) SCALE="scale=-2:1080"; GOP=8; CRF=20 ;;
  *) echo "ERROR: mode must be desktop, mobile or portrait, got '$MODE'" >&2; exit 1 ;;
esac

# Positional beats env var beats the mode default.
CRF="${4:-${SCROLLCRAFT_CRF:-$CRF}}"
case "$CRF" in
  ''|*[!0-9]*) echo "ERROR: crf must be an integer, got '$CRF'" >&2; exit 1 ;;
esac

mkdir -p "$(dirname "$OUT")"

"$FFMPEG" -y -hide_banner -loglevel error -i "$IN" \
  -an \
  -vf "${SCALE}:flags=lanczos,format=yuv420p" \
  -c:v libx264 -profile:v high -preset slow -crf "$CRF" \
  -g "$GOP" -keyint_min "$GOP" -sc_threshold 0 \
  -movflags +faststart \
  "$OUT"

SIZE=$(du -h "$OUT" | cut -f1)
if [ -n "$FFPROBE" ]; then
  DUR=$("$FFPROBE" -v error -show_entries format=duration -of csv=p=0 "$OUT")
else
  DUR="?"; echo "note: no ffprobe found beside $FFMPEG or on PATH; duration not measured" >&2
fi
echo "$OUT  ${SIZE}  ${DUR}s  gop=${GOP}  crf=${CRF}"
