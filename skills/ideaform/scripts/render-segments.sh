#!/usr/bin/env bash
# ideaform · 阶段四：分段渲染 + 断点续跑（长片必用）
#
# 为什么必须分段（stage4-render.md §3 实测）：
#   7 分钟片（12959 帧 @30fps）单次渲染跑到 5824 帧被 delayRender 30s 超时判死。
#   根因不是代码，是 --concurrency=4 时 4 个 chrome 各开 1080p 页面把内存顶爆
#   （本机 16 核 / 7.6G，瓶颈是内存不是 CPU）。
#   分段后：炸一段只重跑一段；已存在且帧数正确的段自动跳过（断点续跑）。
#
# 用法:
#   render-segments.sh <CompositionId> <out.mp4> [选项]
#
#   # 最常用：从 out/timeline.ts 自动读总帧数
#   bash scripts/render-segments.sh IntroWithAudio out/video.mp4
#
#   # 显式指定
#   bash scripts/render-segments.sh IntroWithAudio out/video.mp4 \
#       --total-frames 1414 --seg-frames 700 --concurrency 2
#
# 选项:
#   --total-frames N   总帧数（缺省从 out/timeline.ts 的 TOTAL_FRAMES 读）
#   --seg-frames N     每段帧数（默认 2592；闭区间 --frames=A-B）
#   --concurrency N    Remotion 并发（默认 3；内存吃紧就降 2）
#   --project DIR      Remotion 工程目录（缺省：契约 → $VW_REMOTION_PROJECT → ./remotion）
#   --force            无视已有分段，全部重渲
#   --clean            拼接成功后删除分段文件
#
# 退出码: 0 成功 / 1 渲染或校验失败 / 2 用法或环境问题
set -uo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SELF_DIR/../.." && pwd)"
CONTRACT="${VW_CONTRACT:-${VW_CONFIG_ROOT:-$HOME/.config/ideaform}/toolchain.json}"

c_red=$'\033[31m'; c_grn=$'\033[32m'; c_yel=$'\033[33m'; c_dim=$'\033[2m'; c_off=$'\033[0m'
ok(){   printf '%s✓%s %s\n' "$c_grn" "$c_off" "$*"; }
warn(){ printf '%s!%s %s\n' "$c_yel" "$c_off" "$*"; }
err(){  printf '%s✗%s %s\n' "$c_red" "$c_off" "$*" >&2; }
dim(){  printf '%s%s%s\n' "$c_dim" "$*" "$c_off"; }

die(){ err "$*"; exit 2; }

# ── 参数 ────────────────────────────────────────────────────────────
COMP=""; OUT=""; TOTAL=""; SEG=2592; CONC=3; PROJ=""; FORCE=0; CLEAN=0
while [ $# -gt 0 ]; do
  case "$1" in
    --total-frames) TOTAL="${2:-}"; shift ;;
    --seg-frames)   SEG="${2:-}"; shift ;;
    --concurrency)  CONC="${2:-}"; shift ;;
    --project)      PROJ="${2:-}"; shift ;;
    --force)        FORCE=1 ;;
    --clean)        CLEAN=1 ;;
    -h|--help)      sed -n '2,26p' "$0"; exit 0 ;;
    -*)             die "未知参数: $1" ;;
    *) if [ -z "$COMP" ]; then COMP="$1"; elif [ -z "$OUT" ]; then OUT="$1"; else die "多余参数: $1"; fi ;;
  esac
  shift
done
[ -n "$COMP" ] && [ -n "$OUT" ] || { sed -n '2,26p' "$0"; exit 2; }

# ── 路径一律转绝对（render 要在工程目录下跑，相对路径会错）─────────
case "$OUT" in /*) ;; *) OUT="$PWD/$OUT" ;; esac
case "$PROJ" in /*) ;; *) PROJ="$PWD/$PROJ" ;; esac

# ── 契约：工具路径 + TMPDIR ─────────────────────────────────────────
PY="${VW_PYTHON:-$(command -v python3 || echo /usr/bin/python3)}"
cget(){ [ -f "$CONTRACT" ] && "$PY" -c "
import json,sys
d=json.load(open(sys.argv[1]))
for k in sys.argv[2].split('.'):
    d=(d.get(k) if isinstance(d,dict) else None)
print('' if d is None else d)" "$CONTRACT" "$1" 2>/dev/null; }

FF="$(cget tools.ffmpeg.path)";  FF="${FF:-$(command -v ffmpeg || true)}"
FP="$(cget tools.ffprobe.path)"; FP="${FP:-$(command -v ffprobe || true)}"
NODE="$(cget tools.node.path)";  NODE="${NODE:-$(command -v node || true)}"
PROJ="${PROJ:-$(cget tools.remotion.project)}"; PROJ="${PROJ:-${VW_REMOTION_PROJECT:-./remotion}}"
CHROME="$(cget tools.remotion.browser.resolved)"; CHROME="${CHROME:-${VW_CHROME:-}}"
TMPD="$(cget tmpdir)"; export TMPDIR="${TMPDIR:-${TMPD:-$PWD/.tmp}}"; mkdir -p "$TMPDIR"

[ -n "$FF" ]   || die "找不到 ffmpeg（先跑 ideaform-setup，或设 VW_FFMPEG）"
[ -n "$FP" ]   || die "找不到 ffprobe"
[ -n "$NODE" ] || die "找不到 node"
[ -d "$PROJ" ] || die "Remotion 工程不存在: $PROJ"
CLI="$PROJ/node_modules/.bin/remotion"
[ -f "$CLI" ] || die "找不到 Remotion CLI: $CLI（工程依赖没装？跑 install.sh --only remotion）"

nbframes(){ "$FP" -v error -select_streams v:0 -show_entries stream=nb_frames \
            -of default=nw=1:nk=1 "$1" 2>/dev/null | tr -d ' ,\r\n'; }

# ── 总帧数：缺省从 out/timeline.ts 读 ───────────────────────────────
if [ -z "$TOTAL" ]; then
  for ts in out/timeline.ts "$PWD/out/timeline.ts" "$REPO_ROOT/out/timeline.ts" "$PROJ/src/timeline.ts"; do
    if [ -f "$ts" ]; then
      TOTAL="$(grep -oE 'TOTAL_FRAMES = [0-9]+' "$ts" | grep -oE '[0-9]+' | head -1)"
      [ -n "$TOTAL" ] && { dim "从 $ts 读到 TOTAL_FRAMES=$TOTAL"; break; }
    fi
  done
fi
[ -n "$TOTAL" ] && [ "$TOTAL" -gt 0 ] 2>/dev/null || die "拿不到总帧数：用 --total-frames 指定"

# ── 分段计划 ────────────────────────────────────────────────────────
OUTDIR="$(dirname "$OUT")"; mkdir -p "$OUTDIR"
SEGDIR="$OUTDIR/.segments-$(basename "$OUT" .mp4)"; mkdir -p "$SEGDIR"
NSEG=$(( (TOTAL + SEG - 1) / SEG ))
EXTRA=(); [ -n "$CHROME" ] && [ -x "$CHROME" ] && EXTRA+=(--browser-executable "$CHROME")
if [ ${#EXTRA[@]} -eq 0 ]; then dim "未指定 chrome（契约里没有 browser.resolved）—— Remotion 用默认探测"; fi
# set -u 下空数组展开的保险写法
RENDER_EXTRA=(); [ ${#EXTRA[@]} -gt 0 ] && RENDER_EXTRA=("${EXTRA[@]}")

echo "════════════════════════════════════════════════════════"
echo "  分段渲染（断点续跑）"
echo "════════════════════════════════════════════════════════"
dim "composition : $COMP"
dim "工程        : $PROJ"
dim "输出        : $OUT"
dim "总帧数      : $TOTAL → $NSEG 段 × ≤$SEG 帧（--frames=A-B 为闭区间）"
dim "并发        : $CONC（内存是瓶颈；超时/卡死就降 2）"
dim "TMPDIR      : $TMPDIR  ★ 必须是大盘（/tmp 若是 10MB tmpfs 会 ENOSPC）"
dim "分段目录    : $SEGDIR（帧数正确的段会跳过；--clean 可清）"
echo

t0=$(date +%s)
DONE=0; SKIPPED=0
for ((i=0; i<NSEG; i++)); do
  from=$(( i * SEG )); to=$(( from + SEG - 1 )); [ "$to" -ge "$TOTAL" ] && to=$(( TOTAL - 1 ))
  want=$(( to - from + 1 ))
  chunk="$SEGDIR/chunk_$(printf '%03d' "$i").mp4"
  if [ "$FORCE" = 0 ] && [ -f "$chunk" ]; then
    got="$(nbframes "$chunk")"
    if [ "$got" = "$want" ]; then
      dim "  [段 $((i+1))/$NSEG] $from-$to  帧数 $got ✓ 已存在，跳过"
      SKIPPED=$((SKIPPED+1)); continue
    fi
    warn "  [段 $((i+1))/$NSEG] $from-$to  已有文件帧数 $got ≠ $want → 重渲"
  fi
  printf '  [段 %d/%d] %s-%s（%d 帧）… ' "$((i+1))" "$NSEG" "$from" "$to" "$want"
  seg_t0=$(date +%s)
  # ★ 必须在工程目录下跑：Remotion CLI 靠 cwd 发现 entry point（src/index.ts）
  if ! ( cd "$PROJ" && "$NODE" "$CLI" render "$COMP" "$chunk" \
       --frames="$from-$to" --concurrency="$CONC" --log=error \
       ${RENDER_EXTRA[@]+"${RENDER_EXTRA[@]}"} ) > "$SEGDIR/chunk_$(printf '%03d' "$i").log" 2>&1; then
    echo; err "段 $((i+1)) 渲染失败。日志: $SEGDIR/chunk_$(printf '%03d' "$i").log"
    tail -5 "$SEGDIR/chunk_$(printf '%03d' "$i").log" | sed 's/^/      /'
    if grep -q "browserExecutable" "$SEGDIR/chunk_$(printf '%03d' "$i").log" 2>/dev/null; then
      dim "      → chrome 路径失效：重跑 detect.py --write 刷新契约（docs/05 A3）"
    elif grep -qi "ENOSPC" "$SEGDIR/chunk_$(printf '%03d' "$i").log" 2>/dev/null; then
      dim "      → TMPDIR 太小：source ~/.config/ideaform/env.sh（docs/05 A4）"
    fi
    exit 1
  fi
  got="$(nbframes "$chunk")"
  seg_t1=$(date +%s)
  if [ "$got" != "$want" ]; then
    echo; err "段 $((i+1)) 帧数不符：得到 ${got:-?}，期望 $want（坏段保留在 $chunk，下次重跑会重渲）"
    exit 1
  fi
  echo "帧数 $got ✓  $(( seg_t1 - seg_t0 ))s  ($(awk "BEGIN{printf \"%.1f\", $got / ($seg_t1 - $seg_t0)}") 帧/s)"
  DONE=$((DONE+1))
done

# ── 拼接（同编码参数 → -c copy 无损、秒级）─────────────────────────
echo
dim "→ 拼接 $NSEG 段 → $OUT（concat -c copy，无损）"
LIST="$SEGDIR/list.txt"
: > "$LIST"
for ((i=0; i<NSEG; i++)); do echo "file 'chunk_$(printf '%03d' "$i").mp4'" >> "$LIST"; done
if ! "$FF" -y -v error -f concat -safe 0 -i "$LIST" -c copy "$OUT"; then
  err "拼接失败"; exit 1
fi
got="$(nbframes "$OUT")"
[ "$got" = "$TOTAL" ] || { err "拼完总帧数 $got ≠ $TOTAL"; exit 1; }

t1=$(date +%s)
echo
ok "渲染完成: $OUT  ($(du -h "$OUT" | cut -f1)，$TOTAL 帧)"
ok "耗时 $(( t1 - t0 ))s（新渲 $DONE 段 / 跳过 $SKIPPED 段）"
[ "$CLEAN" = 1 ] && { rm -f "$SEGDIR"/chunk_*.mp4 "$SEGDIR"/chunk_*.log "$LIST"; dim "分段已清理（--clean）"; }
echo
echo "  下一步（音轨集成 + 校验）："
echo "    bash scripts/mix-av.sh --plan-only --voice out/voice.wav --bgm out/bgm.wav --drop 9"
echo "    python3 scripts/verify-video.py video $OUT --frames $TOTAL"
echo "════════════════════════════════════════════════════════"
