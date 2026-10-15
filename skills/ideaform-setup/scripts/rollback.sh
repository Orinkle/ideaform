#!/usr/bin/env bash
# ideaform-setup · 按 install-manifest.jsonl 逆序回滚
#
# 用法:
#   rollback.sh                 # 列出会撤销什么（默认只列不动手）
#   rollback.sh --list          # 同上
#   rollback.sh --dry-run       # 逐条演习，打印将执行的命令
#   rollback.sh --yes           # 真回滚（逆序）
#   rollback.sh --purge-contract --yes   # 连契约一起删（工作流技能会失效！）
#   rollback.sh --only <kind>   # 只撤销某类（pip-install / npm-install / mkdir / ...）
#
# 安全铁律:
#   * 绝不执行任何指向 /mnt/c、/mnt/d 的删除 —— 直接跳过并报警。
#   * 默认只列不动手。真回滚必须显式 --yes。
#   * 逆序执行（后装的先撤），避免依赖倒挂。
set -uo pipefail

CONFIG_ROOT="${VW_CONFIG_ROOT:-$HOME/.config/ideaform}"
MANIFEST="$CONFIG_ROOT/install-manifest.jsonl"
CONTRACT="$CONFIG_ROOT/toolchain.json"
PY="$(command -v python3 || echo /usr/bin/python3)"

MODE=LIST; ONLY=""; PURGE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --list)           MODE=LIST ;;
    --dry-run)        MODE=DRY ;;
    --yes|-y)         MODE=DO ;;
    --purge-contract) PURGE=1 ;;
    --only)           ONLY="${2:-}"; shift ;;
    --only=*)         ONLY="${1#*=}" ;;
    -h|--help)        sed -n '2,17p' "$0"; exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
  shift
done

c_red=$'\033[31m'; c_grn=$'\033[32m'; c_yel=$'\033[33m'; c_dim=$'\033[2m'; c_off=$'\033[0m'
ok(){ printf '%s✓%s %s\n' "$c_grn" "$c_off" "$*"; }
warn(){ printf '%s!%s %s\n' "$c_yel" "$c_off" "$*"; }
err(){ printf '%s✗%s %s\n' "$c_red" "$c_off" "$*" >&2; }
dim(){ printf '%s%s%s\n' "$c_dim" "$*" "$c_off"; }

echo "════════════════════════════════════════════════════════"
echo "  构造主义视频工作流 · 环境回滚"
echo "  清单: $MANIFEST"
echo "════════════════════════════════════════════════════════"

if [ ! -f "$MANIFEST" ]; then
  warn "没有清单文件 —— 说明本环境从未通过 install.sh 装过东西。"
  dim "  什么都不用回滚。若确实装过，检查 VW_CONFIG_ROOT 是否指对（当前 $CONFIG_ROOT）。"
  exit 0
fi

# 读清单（逆序）。用 python3 解析 JSONL，稳。
# 注意：本沙箱没有 /dev/fd，process substitution `< <(...)` 会失败 → 落临时文件。
RB_TMP="$(mktemp "${TMPDIR:-/tmp}/rb.XXXXXX" 2>/dev/null || echo "/tmp/rb.$$")"
"$PY" - "$MANIFEST" "$ONLY" > "$RB_TMP" <<'PYEOF'
import json, sys
path, only = sys.argv[1], sys.argv[2]
recs = []
for ln in open(path, encoding="utf-8"):
    ln = ln.strip()
    if not ln:
        continue
    try:
        r = json.loads(ln)
    except json.JSONDecodeError:
        continue
    if only and r.get("kind") != only:
        continue
    recs.append(r)
for r in reversed(recs):                       # 逆序
    print(json.dumps(r, ensure_ascii=False))
PYEOF
LINES=()
while IFS= read -r _l; do [ -n "$_l" ] && LINES+=("$_l"); done < "$RB_TMP"
rm -f "$RB_TMP"

if [ "${#LINES[@]}" -eq 0 ]; then
  warn "清单里没有匹配的记录${ONLY:+（筛选: $ONLY）}"
  exit 0
fi

echo
echo "将按【逆序】撤销 ${#LINES[@]} 条："
echo "────────────────────────────────────────────────────────"
i=0
BLOCKED=0
for ln in "${LINES[@]}"; do
  i=$((i+1))
  kind=$("$PY" -c "import json,sys;print(json.loads(sys.argv[1]).get('kind','?'))" "$ln")
  tgt=$("$PY" -c "import json,sys;print(json.loads(sys.argv[1]).get('target','?'))" "$ln")
  det=$("$PY" -c "import json,sys;print(json.loads(sys.argv[1]).get('detail',''))" "$ln")
  undo=$("$PY" -c "import json,sys;print(json.loads(sys.argv[1]).get('undo',''))" "$ln")
  printf '%2d. [%s] %s\n' "$i" "$kind" "$tgt"
  [ -n "$det" ] && dim "      原因: $det"
  if [ -z "$undo" ] || [ "$undo" = "null" ]; then
    warn "      无撤销命令 → 需手工处理"
    BLOCKED=$((BLOCKED+1))
    continue
  fi
  case "$undo" in
    *"/mnt/c"*|*"/mnt/d"*)
      err "      撤销命令指向 Windows 盘，已拒绝执行"
      BLOCKED=$((BLOCKED+1)); continue ;;
  esac
  dim "      撤销: $undo"
  if [ "$MODE" = DO ]; then
    if bash -c "$undo" >/dev/null 2>&1; then ok "      已撤销"; else warn "      撤销失败（可能已不存在）"; fi
  fi
done
echo "────────────────────────────────────────────────────────"

if [ "$PURGE" = 1 ]; then
  echo
  warn "⚠ --purge-contract：将删除契约文件"
  echo "    $CONTRACT"
  dim "  删掉之后工作流技能就读不到工具链路径了（需要重跑环境配置技能）。"
  if [ "$MODE" = DO ]; then
    if [ -f "$CONTRACT" ]; then
      mkdir -p "$CONFIG_ROOT/backup"
      cp -a "$CONTRACT" "$CONFIG_ROOT/backup/toolchain.json.$(date +%Y%m%d-%H%M%S)"
      rm -f "$CONTRACT" "$CONFIG_ROOT/env.sh"
      ok "契约已删（备份留在 $CONFIG_ROOT/backup/）"
    else
      dim "  契约本就不存在"
    fi
  fi
fi

echo
case "$MODE" in
  LIST)
    echo "（以上为清单，未执行任何操作）"
    echo "  演习: rollback.sh --dry-run"
    echo "  真回滚: rollback.sh --yes"
    ;;
  DRY)
    echo "（演习结束，未执行任何操作）"
    echo "  真回滚: rollback.sh --yes"
    ;;
  DO)
    if [ "$BLOCKED" -gt 0 ]; then
      warn "有 $BLOCKED 条需手工处理 —— 见上方标注"
    else
      ok "回滚完成"
    fi
    echo "  建议随后重跑: detect.py   核对残留"
    ;;
esac
echo "════════════════════════════════════════════════════════"
