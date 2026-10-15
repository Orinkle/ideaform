#!/usr/bin/env bash
# ideaform-setup · 补装缺失工具链
#
# 用法:
#   install.sh                      # 装所有 missing 项（会先问你）
#   install.sh --only lmms,venv     # 只装指定项
#   install.sh --dry-run            # 只看会做什么，不动手
#   install.sh --yes                # 不逐项确认
#
# 铁律:
#   * 装之前把将被覆盖的已有文件备份到 $VW_CONFIG_ROOT/backup/<ts>/
#   * 每完成一步就向 install-manifest.jsonl 追加一条（append-only，天然可回滚）
#   * 全部落用户级路径，无需 root。需要 root 的活 —— 打印命令交给用户，不自己试 sudo。
set -uo pipefail

CONFIG_ROOT="${VW_CONFIG_ROOT:-$HOME/.config/ideaform}"
CONTRACT="$CONFIG_ROOT/toolchain.json"
MANIFEST="$CONFIG_ROOT/install-manifest.jsonl"
LOG_DIR="$CONFIG_ROOT/logs"
TS="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$CONFIG_ROOT/backup/$TS"
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$(command -v python3 || echo /usr/bin/python3)"

DRY=0; YES=0; ONLY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --yes|-y)  YES=1 ;;
    --only)    ONLY="${2:-}"; shift ;;
    --only=*)  ONLY="${1#*=}" ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
  shift
done

mkdir -p "$CONFIG_ROOT" "$LOG_DIR" "$BACKUP_DIR"

# ---------------------------------------------------------------- 基础工具
c_red=$'\033[31m'; c_grn=$'\033[32m'; c_yel=$'\033[33m'; c_dim=$'\033[2m'; c_off=$'\033[0m'
log()  { printf '%s\n' "$*"; }
ok()   { printf '%s✓%s %s\n' "$c_grn" "$c_off" "$*"; }
warn() { printf '%s!%s %s\n' "$c_yel" "$c_off" "$*"; }
err()  { printf '%s✗%s %s\n' "$c_red" "$c_off" "$*" >&2; }
dim()  { printf '%s%s%s\n' "$c_dim" "$*" "$c_off"; }

want() {   # want <name> → 是否在 --only 白名单里
  [ -z "$ONLY" ] && return 0
  case ",$ONLY," in *",$1,"*) return 0 ;; *) return 1 ;; esac
}

# 向 manifest 追加一条（JSONL）。字段: kind target detail undo
record() {
  local kind="$1" target="$2" detail="$3" undo="$4"
  [ "$DRY" = 1 ] && { dim "[dry-run] record $kind $target"; return 0; }
  "$PY" - "$MANIFEST" "$kind" "$target" "$detail" "$undo" <<'PYEOF'
import json, sys, time, os
path, kind, target, detail, undo = sys.argv[1:6]
rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "kind": kind,
       "target": target, "detail": detail, "undo": undo}
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "a", encoding="utf-8") as f:
    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
PYEOF
}

# 覆盖已有文件前先备份
backup_file() {
  local f="$1"
  [ -e "$f" ] || return 0
  [ "$DRY" = 1 ] && { dim "[dry-run] backup $f"; return 0; }
  mkdir -p "$BACKUP_DIR"
  cp -a "$f" "$BACKUP_DIR/$(basename "$f")"
  ok "已备份 $(basename "$f") → $BACKUP_DIR/"
  record "backup-file" "$f" "备份于 $BACKUP_DIR/$(basename "$f")" \
         "cp -a '$BACKUP_DIR/$(basename "$f")' '$f'"
}

# 用户级目录创建（可回滚）
mk_userdir() {
  local d="$1"
  [ -d "$d" ] && return 0
  [ "$DRY" = 1 ] && { dim "[dry-run] mkdir -p $d"; return 0; }
  mkdir -p "$d"
  record "mkdir" "$d" "新建目录" "rm -rf '$d'"
}

# 从契约里取字段
cget() {
  [ -f "$CONTRACT" ] || { echo ""; return; }
  "$PY" -c "
import json,sys
d=json.load(open(sys.argv[1]))
for k in sys.argv[2].split('.'):
    d=(d or {}).get(k) if isinstance(d,dict) else None
print('' if d is None else d)" "$CONTRACT" "$1" 2>/dev/null
}

confirm() {
  [ "$YES" = 1 ] && return 0
  [ "$DRY" = 1 ] && return 0
  printf '%s [y/N] ' "$1"
  read -r a </dev/tty 2>/dev/null || read -r a || a=n
  case "$a" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

echo "════════════════════════════════════════════════════════"
echo "  构造主义视频工作流 · 工具链补装"
[ "$DRY" = 1 ] && echo "  （dry-run 模式：只演示，不落盘）"
echo "  契约     : $CONTRACT"
echo "  清单     : $MANIFEST"
echo "  备份     : $BACKUP_DIR"
echo "════════════════════════════════════════════════════════"

if [ ! -f "$CONTRACT" ] && [ "$DRY" = 0 ]; then
  warn "未找到契约，先跑一次只读探测以确定缺什么"
  "$PY" "$SELF_DIR/detect.py" --write --workspace "$PWD" || true
fi

TMPDIR_BIG="$(cget tmpdir)"; TMPDIR_BIG="${TMPDIR_BIG:-$PWD/.tmp}"
export TMPDIR="$TMPDIR_BIG"; mkdir -p "$TMPDIR"
dim "TMPDIR=$TMPDIR  （必须是大盘；本机 /tmp 只有 10MB，装包会 ENOSPC）"

VENV_PY="$(cget tools.venv.python)"
VENV_PIP="$(cget tools.venv.pip)"
REMOTION_PROJ="$(cget tools.remotion.project)"
REMOTION_IS_TEMPLATE="$(cget tools.remotion.is_bundled_template)"
NODE_BIN="$(cget tools.node.path)"
NPX_DIR="$(dirname "$NODE_BIN" 2>/dev/null)"

FAILED=()

# ---------------------------------------------------------------- 1. venv 包
install_venv() {
  want venv || return 0
  echo; log "── [1/4] venv Python 包 ────────────────────────────"
  if [ -z "$VENV_PY" ] || [ ! -x "$VENV_PY" ]; then
    err "契约里没有可用 venv（tools.venv.python 为空）。"
    dim "  手工建一个:  python3 -m venv \"$CONFIG_ROOT/venv\"  然后 VW_VENV=... 重跑 detect.py"
    FAILED+=("venv"); return 1
  fi
  local pkgs_missing
  pkgs_missing=$("$PY" -c "
import json,sys
d=json.load(open(sys.argv[1]))
p=d['tools'].get('packages',{})
need=[k for k,v in p.items() if not v.get('present')]
print(' '.join(need))" "$CONTRACT" 2>/dev/null)
  # edge-tts 无论装没装都检查版本（< 7.3.1 会 403）
  local items=""
  for m in edge-tts soundfile numpy; do
    case " $pkgs_missing " in *" $m "*) items="$items $m" ;; esac
  done
  items="${items:-} edge-tts"     # 强制复核 edge-tts
  dim "  待装/待升级:$items"
  local spec
  case "$items" in
    *edge-tts*) spec='"edge-tts>=7.3.1"' ;;
    *) spec='' ;;
  esac
  local args=""
  case " $pkgs_missing " in *" soundfile "*) args="$args soundfile" ;; esac
  case " $pkgs_missing " in *" numpy "*)     args="$args numpy" ;; esac
  [ -n "$spec" ] && args="$args $spec"
  [ -z "${args// /}" ] && { ok "venv 包已齐，跳过"; return 0; }

  confirm "用 pip 装:$args ?" || { warn "跳过 venv"; return 0; }
  if [ "$DRY" = 0 ]; then
    # shellcheck disable=SC2086
    if "$VENV_PIP" install --disable-pip-version-check -q $args 2>&1 | tail -5; then
      ok "pip 安装完成"
      record "pip-install" "$VENV_PY" "$args" \
             "'$VENV_PIP' uninstall -y $(echo "$args" | tr -d '\"' | sed 's/[><=].*//g')"
    else
      err "pip 安装失败"; FAILED+=("venv"); return 1
    fi
  fi
}

# ---------------------------------------------------------------- 2. Remotion 依赖
install_remotion() {
  want remotion || return 0
  echo; log "── [2/4] Remotion 依赖 ─────────────────────────────"
  if [ -z "$REMOTION_PROJ" ]; then
    err "契约里没有 Remotion 工程。"
    dim "  自带模板: $SELF_DIR/../assets/templates/remotion-starter/"
    FAILED+=("remotion"); return 1
  fi
  dim "  工程: $REMOTION_PROJ"
  if [ "$REMOTION_IS_TEMPLATE" = "True" ]; then
    local dst="$CONFIG_ROOT/remotion-project"
    mk_userdir "$dst"
    if [ "$DRY" = 0 ]; then
      cp -a "$SELF_DIR/../assets/templates/remotion-starter/." "$dst/"
      ok "已把自带模板复制到 $dst"
      record "copy-dir" "$dst" "来自技能自带模板" "rm -rf '$dst'"
      REMOTION_PROJ="$dst"
    fi
  fi
  [ -d "$REMOTION_PROJ/node_modules/remotion" ] && { ok "依赖已在，跳过"; return 0; }
  confirm "在 $REMOTION_PROJ 跑 npm install ?" || { warn "跳过"; return 0; }
  if [ "$DRY" = 0 ]; then
    ( cd "$REMOTION_PROJ" && PATH="$NPX_DIR:$PATH" npm install --no-audit --no-fund 2>&1 | tail -8 )
    record "npm-install" "$REMOTION_PROJ" "npm install" "rm -rf '$REMOTION_PROJ/node_modules'"
    [ -d "$REMOTION_PROJ/node_modules/remotion" ] && ok "npm 安装完成" \
      || { err "npm 安装后仍找不到 remotion"; FAILED+=("remotion"); }
  fi
}

# ---------------------------------------------------------------- 3. LMMS
install_lmms() {
  want lmms || return 0
  echo; log "── [3/4] LMMS 1.2.2（AppImage 解包）─────────────────"
  local root="$CONFIG_ROOT/lmms"
  local apprun="$root/squashfs-root/AppRun"
  if [ -x "$apprun" ]; then
    ok "LMMS 已在: $apprun"
  else
    mk_userdir "$root"
    local url="https://gh-proxy.com/https://github.com/LMMS/lmms/releases/download/v1.2.2/lmms-1.2.2-linux-x86_64.AppImage"
    local want_bytes=96362536
    dim "  来源(走代理，直连只有 ~10KB/s): $url"
    dim "  期望字节: $want_bytes  （实测 19.85MB/s，约 5 秒）"
    confirm "下载并解包 LMMS（约 336MB 磁盘）?" || { warn "跳过 lmms"; FAILED+=("lmms"); return 1; }
    if [ "$DRY" = 0 ]; then
      ( cd "$root" && curl -fL --retry 3 --retry-delay 2 -o lmms.AppImage "$url" ) \
        || { err "下载失败"; FAILED+=("lmms"); return 1; }
      local got; got=$(stat -c %s "$root/lmms.AppImage" 2>/dev/null || echo 0)
      if [ "$got" != "$want_bytes" ]; then
        err "字节数不符（得 $got，期望 $want_bytes）→ 删残骸，请重试"
        rm -f "$root/lmms.AppImage"; FAILED+=("lmms"); return 1
      fi
      ok "下载完成且字节数校验通过"
      record "mkdir" "$root" "LMMS 安装目录" "rm -rf '$root'"
      chmod +x "$root/lmms.AppImage"
      # 沙箱无 /dev/fuse → 必须解包
      ( cd "$root" && ./lmms.AppImage --appimage-extract >/dev/null 2>&1 ) \
        || { err "解包失败（缺 /dev/fuse? 用 --appimage-extract 是对的）"; FAILED+=("lmms"); return 1; }
      rm -f "$root/lmms.AppImage"
      ok "解包完成: $root/squashfs-root/"
      record "lmms-extract" "$apprun" "AppImage 解包" "rm -rf '$root/squashfs-root'"
    fi
  fi

  # stkdir 配置 —— 最贵的坑：指向错目录会全程静音且不报错
  local stk="$root/squashfs-root/usr/share/stk/rawwaves"
  local rc="$HOME/.lmmsrc.xml"
  if [ -d "$stk" ]; then
    if [ ! -f "$rc" ]; then
      if [ "$DRY" = 0 ]; then
        printf '<?xml version="1.0"?>\n<!DOCTYPE lmms-config-file>\n<lmms version="1.2.2">\n  <paths stkdir="%s/" workingdir="%s/"/>\n</lmms>\n' \
          "$stk" "$root" > "$rc"
        ok "已创建 ~/.lmmsrc.xml（stkdir 指向解包目录）"
        record "create-file" "$rc" "LMMS 配置，stkdir=$stk/" "rm -f '$rc'"
      fi
    elif ! grep -q "$stk" "$rc" 2>/dev/null; then
      backup_file "$rc"
      if [ "$DRY" = 0 ]; then
        if grep -q 'stkdir=' "$rc"; then
          "$PY" - "$rc" "$stk/" <<'PYEOF'
import re,sys
p,stk=sys.argv[1],sys.argv[2]
s=open(p,encoding="utf-8").read()
s=re.sub(r'stkdir="[^"]*"', 'stkdir="%s"' % stk, s)
open(p,"w",encoding="utf-8").write(s)
PYEOF
        fi
        ok "已改 ~/.lmmsrc.xml 的 stkdir"
        # 回滚 = 从备份还原（改文件类一律用备份还原，不做反向字符串替换）
        bkp="$BACKUP_DIR/$(basename "$rc")"
        if [ -f "$bkp" ]; then
          record "edit-file" "$rc" "stkdir → $stk/" "cp -a '$bkp' '$rc'"
        else
          record "edit-file" "$rc" "stkdir → $stk/" "（无备份；请手工改回原 stkdir）"
        fi
      fi
    else
      ok "stkdir 已正确指向解包目录"
    fi
  else
    warn "找不到 $stk（波表目录）—— LMMS 可能全程静音"
  fi
}

# ---------------------------------------------------------------- 4. 字体 / ffmpeg
install_misc() {
  want fonts && {
    echo; log "── [4/4] 中文字体 & ffmpeg ─────────────────────────"
    local fams; fams=$(cget tools.fonts.count_zh)
    if [ "${fams:-0}" -gt 0 ]; then
      ok "已有 $fams 个中文字族，跳过"
    else
      warn "未探测到中文字体 —— 中文会渲染成豆腐块"
      dim "  用户级安装:  下载 .ttc/.ttf → cp 到 ~/.local/share/fonts/ → fc-cache -f"
      dim "  （字体来源因发行版而异，本脚本不代为下载）"
      FAILED+=("fonts")
    fi
  }
  want ffmpeg-full && {
    warn "完整版 ffmpeg 为可选项；本脚本不代为下载（上游地址未实测）。"
    dim "  精简版够用就别装 —— 少一个变量。"
  }
}

# ---------------------------------------------------------------- 主流程
install_venv
install_remotion
install_lmms
install_misc

echo
echo "════════════════════════════════════════════════════════"
if [ "${#FAILED[@]}" -gt 0 ]; then
  err "未完成: ${FAILED[*]}"
  dim "  修好后重跑本脚本，或手工处理（见 references/toolchain-matrix.md）"
else
  ok "补装流程结束"
fi
[ "$DRY" = 0 ] && dim "清单已追加: $MANIFEST   （回滚: rollback.sh）"
echo "════════════════════════════════════════════════════════"
echo
echo "下一步：重跑探测刷新契约 → 再跑冒烟校验"
echo "  $PY $SELF_DIR/detect.py --write"
echo "  $PY $SELF_DIR/verify.py"
exit 0
