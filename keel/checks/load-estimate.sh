#!/usr/bin/env bash
# load-estimate.sh —— 把检索协议第 4 条变成可执行命令（《Keel 设计稿》§7.2 全局口径 / §8）
# 用法: bash keel/checks/load-estimate.sh <关键词> [更多关键词…] [--list]
# 退出码: 0 = 本轮估算在预算内；1 = 超预算；2 = 用法错误
#
# 为什么要它：
#   §7.1 只约束"单个文件多大"，真正会被击穿的口径是 **§7.2 的单轮总量**
#   ——真实会话里超预算最常见的方式不是"读了篇大文档"，而是 grep 命中十几个文件后顺手全读。
#   §8 协议第 4 条写了"≤15,000 字节"，但此前没有任何方式能验它。
#   本脚本按协议口径把这一轮要读的量算出来，超了就红——于是它从建议变成了命令。
#
# 口径（与 §8 协议第 1、2、4 条一致）：
#   固定成本 = INDEX.md + 当前 NOW*.md
#   按需     = grep -rlF <关键词> 命中的 md（冷区不计）
#   总量     = 两者之和，上限取自 budget.env 的 BYTES_SESSION（唯一真源）
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
KEEL=$(cd "$HERE/.." && pwd)

[ -f "$KEEL/checks/budget.env" ] || { echo "❌ 缺预算真源 checks/budget.env（§9.3）"; exit 2; }
. "$KEEL/checks/budget.env"
BYTES_SESSION=${BYTES_SESSION:-15000}

LIST=0
kws=()
for a in "$@"; do
  case "$a" in
    --list) LIST=1 ;;
    -*) echo "❌ 未知参数: $a"; exit 2 ;;
    *) kws+=("$a") ;;
  esac
done
[ "${#kws[@]}" -ge 1 ] || { echo "用法: bash keel/checks/load-estimate.sh <关键词> [更多关键词…] [--list]"; exit 2; }

b_of() { wc -c < "$1" 2>/dev/null | tr -d '[:space:]'; }

# 固定成本：INDEX.md + 当前 NOW*.md（不存在时按 0 计，缺文件由 lint 负责报）
fixed=0
if [ -f "$KEEL/INDEX.md" ]; then n=$(b_of "$KEEL/INDEX.md"); fixed=$((fixed + n)); fi
nows=""
for f in "$KEEL"/NOW*.md; do
  [ -f "$f" ] || continue
  n=$(b_of "$f"); fixed=$((fixed + n)); nows="$nows $f"
done

# 按需：grep -F 逐关键词 OR（-F 避免关键词里的正则元字符被误解析）
args=()
for k in "${kws[@]}"; do args+=(-e "$k"); done
hits=$(grep -rlF "${args[@]}" "$KEEL" --include='*.md' \
         --exclude-dir=archive --exclude-dir=NOW-history 2>/dev/null | sort -u || true)

ondemand=0; listed=0
for f in $hits; do
  case "$f" in
    "$KEEL/INDEX.md"|"$KEEL"/NOW*.md) continue ;;   # 已在固定成本里，不重复计
  esac
  n=$(b_of "$f"); ondemand=$((ondemand + n)); listed=$((listed + 1))
  [ "$LIST" -eq 1 ] && printf '      %6s  %s\n' "$n" "${f#"$KEEL"/}"
done

total=$((fixed + ondemand))
echo "load-estimate · 目录=$KEEL · 预算（BYTES_SESSION）=$BYTES_SESSION 字节"
echo "  固定成本 INDEX+NOW      : $fixed"
echo "  按需命中（$listed 个文件）: $ondemand"
echo "  ─────────────────────────────"
printf '  本轮合计                : %s 字节  ≈ %s token（按 3 字节/token，§7.1）\n' "$total" "$((total / 3))"

if [ "$total" -gt "$BYTES_SESSION" ]; then
  echo "❌ 超预算 ${total}>${BYTES_SESSION}：先收窄关键词，不要顺手全读（§7.3 拆 / 提 / 沉）"
  exit 1
fi
echo "✅ 在预算内（余量 $((BYTES_SESSION - total)) 字节）"
exit 0
