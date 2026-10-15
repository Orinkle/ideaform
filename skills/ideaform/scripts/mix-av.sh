#!/usr/bin/env bash
# ideaform · 阶段四：音轨集成
#
# 两条路线，按需选：
#   A. Remotion 集成（推荐，也是本项目默认）
#      composition 里用 <Audio src={voice}/> + <Audio src={bgm} volume={V}/>，
#      渲染出的 mp4 自带音轨。本脚本 --plan-only 帮你算出那个 V。
#   B. 后合成（视频已渲好 / 需要重配音时）
#      无声 mp4 + 解说 wav + BGM wav → 成片。本脚本主流程。
#
# 用法:
#   # 只算 BGM 该压多少（打印可直接抄进 <Audio volume={...}> 的值）
#   mix-av.sh --plan-only --voice voice.wav --bgm bgm.wav [--drop 9]
#
#   # 后合成
#   mix-av.sh --video silent.mp4 --voice voice.wav --bgm bgm.wav --out final.mp4
#
# 依据（实测）：BGM 应比旁白低 8~12 dB 才是「衬底」而不是「伴奏」。
#   RATE=0.17 只压到之下 5.6 dB，对密集口播明显偏吵。
set -uo pipefail

VOICE=""; BGM=""; VIDEO=""; OUT="final.mp4"; DROP=9.0; PLAN_ONLY=0; KEEP_TMP=0
CONTRACT="${VW_CONTRACT:-${VW_CONFIG_ROOT:-$HOME/.config/ideaform}/toolchain.json}"

while [ $# -gt 0 ]; do
  case "$1" in
    --voice) VOICE="${2:-}"; shift ;;
    --bgm)   BGM="${2:-}"; shift ;;
    --video) VIDEO="${2:-}"; shift ;;
    --out)   OUT="${2:-}"; shift ;;
    --drop)  DROP="${2:-}"; shift ;;
    --plan-only) PLAN_ONLY=1 ;;
    --keep-tmp)  KEEP_TMP=1 ;;
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
  shift
done

c_red=$'\033[31m'; c_grn=$'\033[32m'; c_yel=$'\033[33m'; c_dim=$'\033[2m'; c_off=$'\033[0m'
ok(){ printf '%s✓%s %s\n' "$c_grn" "$c_off" "$*"; }
warn(){ printf '%s!%s %s\n' "$c_yel" "$c_off" "$*"; }
err(){ printf '%s✗%s %s\n' "$c_red" "$c_off" "$*" >&2; }
dim(){ printf '%s%s%s\n' "$c_dim" "$*" "$c_off"; }

# ── 工具路径：优先契约，其次环境变量，最后 PATH ──────────────────
# 注意顺序：cget 依赖 PY，所以 PY 必须先有一个引导值。
PY="${VW_PYTHON:-$(command -v python3 || echo /usr/bin/python3)}"
cget(){ [ -f "$CONTRACT" ] && "$PY" -c "
import json,sys
d=json.load(open(sys.argv[1]))
for k in sys.argv[2].split('.'):
    d=(d or {}).get(k) if isinstance(d,dict) else None
print('' if d is None else d)" "$CONTRACT" "$1" 2>/dev/null; }

PY="$(cget tools.venv.python)"; PY="${PY:-${VW_PYTHON:-python3}}"
FF="$(cget tools.ffmpeg.path)"; FF="${FF:-$(command -v ffmpeg || true)}"
FP="$(cget tools.ffprobe.path)"; FP="${FP:-$(command -v ffprobe || true)}"
TMPD="$(cget tmpdir)"; export TMPDIR="${TMPDIR:-${TMPD:-$PWD/.tmp}}"; mkdir -p "$TMPDIR"

[ -z "$FF" ] && { err "找不到 ffmpeg（设 VW_FFMPEG 或先跑环境配置技能）"; exit 2; }
[ -z "$FP" ] && { err "找不到 ffprobe"; exit 2; }
[ -n "$VOICE" ] && [ ! -f "$VOICE" ] && { err "解说音轨不存在: $VOICE"; exit 2; }
[ -n "$BGM" ]   && [ ! -f "$BGM" ]   && { err "BGM 不存在: $BGM"; exit 2; }

# ── 实测 RMS（Remotion 精简版 ffmpeg 没有 volumedetect → 自己算）──
rms_db(){ "$PY" - "$1" <<'PYEOF'
import wave, array, math, sys, os, subprocess
p = sys.argv[1]
tmp = None
if not p.lower().endswith(".wav"):
    # 非 WAV 先解成 WAV（用 ffmpeg，路径走环境变量）
    ff = os.environ.get("VW_FFMPEG") or os.environ.get("FFMPEG") or "ffmpeg"
    tmp = p + ".rms.wav"
    subprocess.run([ff, "-y", "-v", "error", "-i", p, "-ac", "1", "-ar", "48000",
                    "-c:a", "pcm_s16le", tmp], check=True)
    p = tmp
try:
    with wave.open(p) as w:
        nch, n = w.getnchannels(), w.getnframes()
        a = array.array("h"); a.frombytes(w.readframes(n))
    mono = [(a[i]+a[i+1])*0.5 for i in range(0, len(a)-nch+1, nch)] if nch > 1 else list(a)
    rms = math.sqrt(sum(x*x for x in mono)/len(mono)) if mono else 0.0
    print(f"{20*math.log10(rms/32768):.2f}" if rms > 0 else "-99.00")
finally:
    if tmp and os.path.exists(tmp):
        os.remove(tmp)
PYEOF
}

gain_of(){ "$PY" -c "
import sys
drop, v, b = float(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3])
gain = (v - drop) - b          # 想让 BGM 落在旁白之下 drop dB，需要加多少 dB
print(f'{gain:.2f}', f'{10**(gain/20):.4f}')" "$1" "$2" "$3"; }

echo "════════════════════════════════════════════════════════"
echo "  音轨集成"
echo "════════════════════════════════════════════════════════"

VR=""; BR=""
[ -n "$VOICE" ] && { VR="$(rms_db "$VOICE")"; dim "解说 RMS = ${VR} dBFS   ($(basename "$VOICE"))"; }
[ -n "$BGM" ]   && { BR="$(rms_db "$BGM")";   dim "BGM  RMS = ${BR} dBFS   ($(basename "$BGM"))"; }

if [ -n "$VR" ] && [ -n "$BR" ]; then
  read -r GDB GFAC <<<"$(gain_of "$DROP" "$VR" "$BR")"
  echo
  echo "  目标：BGM 比旁白低 ${DROP} dB（纪录片/解说衬底常用 8~12 dB）"
  echo "  → BGM 需加 ${GDB} dB  →  线性增益 volume = ${GFAC}"
fi

if [ "$PLAN_ONLY" = 1 ]; then
  echo
  echo "  ── 路线 A（Remotion 集成）照抄："
  echo "     <Audio src={staticFile(\"bgm.wav\")} volume={${GFAC:-0.12}} />"
  echo "     <Audio src={staticFile(\"voice.wav\")} />"
  dim "  说明：Remotion 渲出的 mp4 自带音轨，无需再 -map 合流。"
  echo "  校验（渲完必做）："
  echo "     $FP -v error -select_streams a:0 -show_entries stream=bit_rate \\"
  echo "        -of default=nw=1:nk=1 out.mp4     # 应 > 64000"
  exit 0
fi

[ -z "$VIDEO" ] && { err "后合成需要 --video（无声 mp4）"; exit 2; }
[ ! -f "$VIDEO" ] && { err "视频不存在: $VIDEO"; exit 2; }

# ── 路线 B：后合成（必须显式 -map，否则会挑中 Remotion 自带的静音轨）──
echo
dim "→ 路线 B 后合成（显式 -map 0:v:0 -map 1:a:0 …）"
if [ -n "$BGM" ] && [ -n "$BR" ]; then
  read -r GDB GFAC <<<"$(gain_of "$DROP" "$VR" "$BR")"
  "$FF" -y -v error -i "$VIDEO" -i "$VOICE" -i "$BGM" \
        -filter_complex "[2:a]volume=${GFAC}[bg];[1:a][bg]amix=inputs=2:duration=first:dropout_transition=0[ax]" \
        -map 0:v:0 -map "[ax]" \
        -c:v copy -c:a aac -b:a 192k -ar 48000 -ac 2 -shortest "$OUT" \
    || { err "合流失败"; exit 1; }
else
  warn "缺 voice 或 bgm，退化为单音轨合流"
  "$FF" -y -v error -i "$VIDEO" -i "${VOICE:-$BGM}" \
        -map 0:v:0 -map 1:a:0 \
        -c:v copy -c:a aac -b:a 192k -ar 48000 -ac 2 -shortest "$OUT" \
    || { err "合流失败"; exit 1; }
fi

# ── 自检（必做）──────────────────────────────────────────────
echo
AB="$("$FP" -v error -select_streams a:0 -show_entries stream=bit_rate -of default=nw=1:nk=1 "$OUT" | tr -d ' ,\r\n')"
NB="$("$FP" -v error -select_streams v:0 -show_entries stream=nb_frames -of default=nw=1:nk=1 "$OUT" | tr -d ' ,\r\n')"
DUR="$("$FP" -v error -select_streams a:0 -show_entries stream=duration -of default=nw=1:nk=1 "$OUT" | tr -d ' ,\r\n')"
echo "  音轨码率 $AB bps    帧数 $NB    音轨时长 ${DUR}s"
if [ "${AB:-0}" -gt 64000 ]; then ok "音轨非静音"; else err "音轨疑似静音（${AB} bps）→ 检查 -map"; fi
ok "成片: $OUT  ($(du -h "$OUT" | cut -f1))"
echo
echo "  下一步：校验成片"
echo "    $PY skills/ideaform/scripts/verify-video.py video $OUT --frames $NB"
echo "════════════════════════════════════════════════════════"
