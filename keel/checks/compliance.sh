#!/usr/bin/env bash
# compliance.sh —— 遵守率度量（Keel 设计稿 §11.2，ADR 0009）
# 用法:
#   bash keel/checks/compliance.sh record            # 记录一轮（钩子自动调用，一般不手动跑）
#   bash keel/checks/compliance.sh report [--json]   # 出报告：总轮次 / 命中轮次 / 遵守率
#   bash keel/checks/compliance.sh reset             # 清空（换基线时用）
# 退出码: 0 = 正常；1 = 用法错误
#
# ── 为什么是这个口径 ──────────────────────────────────────────────
# 调研（2026-10，逐个读源码而非读 README）确认**没有任何项目真正实现了
# "度量 AI 是否遵守规则"**：
#   · dsh-rule-lens 面板写"遵守率"，但数据结构里只有拦截计数、没有分母——
#     加载 10 条违反 1 条 → 拦截 0 次 → 显示"0 次拦截"，读起来像 100% 遵守。
#     数字方向是反的，比没有数字更危险。
#   · aegis 让 AI 自报（adapter 规则第 5 步 "Self-Review"）。
#   · holaOS 全仓 grep 遵守率 → 零实现。
#
# 而 holaOS 的一份 223 行取证文档给出了最关键的反例：
#   **门禁全部正确触发、AI 对目标目录零编辑、然后宣布任务完成。**
#   它试过加重门禁措辞 → 得到**更精致的形式合规**。
#
# 所以本脚本**不读 AI 的任何自述**。它只观测两件客观事实：
#   1. 这一轮 lint 报了几条 ❌ / ⚠️        （来自 keel-lint.sh 的真实输出）
#   2. 这一轮提交动了哪些文件             （来自 git diff --cached）
# 两个数据源都不经过 AI，**AI 一个都改不了**。
#
# ── 分子分母的定义（这是全部的关键）──────────────────────────────
#   分母 = 记录过的总轮次（每次 pre-commit 记一条）
#   分子 = 至少命中一条检查项的轮次数
#   遵守率 = 1 − 分子/分母
#
#   **故意不把"命中条数"当分子**：一次提交踩 3 条和踩 1 条，
#   对"这轮守没守规矩"是同一件事（没守住）。按条数算会让数字随检查项
#   数量漂移——加一条检查项就能让历史遵守率"变差"，那是指标自己骗自己。
#
# ── 这个指标会骗人的地方（请连同数字一起读）────────────────────────
#   1. **规则本身可能不可遵守**。若某条规则 §2 原则 4 判死不了，
#      遵守率低不代表 AI 不听话，可能代表规则写得不对。**低遵守率时先查规则。**
#   2. **只覆盖被钩子触发的轮次**。没提交就不记，所以它量的是
#      "提交时的合规率"，不是"所有工作的合规率"。
#   3. **没有基线就没有意义**。第一次跑出来的数字别当成绩。
set -uo pipefail

KEEL_DIR="keel"
[ -d "$KEEL_DIR/checks" ] || { echo "❌ 不像 keel 目录（缺 $KEEL_DIR/checks）"; exit 1; }
. "$KEEL_DIR/checks/budget.env" 2>/dev/null || true

# 指标数据不进版本库（它是本机观测，不是规格）——故放 checks/.metrics/
METRICS="$KEEL_DIR/checks/.metrics"
VIO="$METRICS/violations.jsonl"
LOAD="$METRICS/load.jsonl"
mkdir -p "$METRICS" 2>/dev/null || true

cmd="${1:-report}"
shift 2>/dev/null || true

# ── record：记一轮 ──────────────────────────────────────────────
# 参数（由 pre-commit 传入）：--fails N --warns N --files N
record() {
  local fails=0 warns=0 files=0
  while [ $# -gt 0 ]; do
    case "$1" in
      --fails) fails="${2:-0}"; shift 2 ;;
      --warns) warns="${2:-0}"; shift 2 ;;
      --files) files="${2:-0}"; shift 2 ;;
      *) shift ;;
    esac
  done
  [ -f "$VIO" ] || : > "$VIO"
  local ts commit
  ts=$(date '+%Y-%m-%dT%H:%M:%S%z')
  commit=$(git rev-parse --short HEAD 2>/dev/null || echo "-")
  # 只记数字与事实，不记 AI 的任何自述
  printf '%s\tcommit=%s\tfails=%s\twarns=%s\tfiles=%s\n' \
    "$ts" "$commit" "$fails" "$warns" "$files" >> "$VIO"
}

# ── report：出报告 ──────────────────────────────────────────────
report() {
  local as_json=0
  for a in "$@"; do [ "$a" = "--json" ] && as_json=1; done

  if [ ! -s "$VIO" ]; then
    if [ "$as_json" -eq 1 ]; then
      printf '{"rounds":0,"violating":0,"rate":null,"note":"no data"}\n'
    else
      echo "compliance · 还没有任何记录"
      echo "   记录由 pre-commit 自动写入；先提交一次（哪怕 --no-verify 也会记）再来看。"
    fi
    return 0
  fi

  # 一次 awk 算完：轮次、命中轮次、累计 fails/warns/files
  local agg
  agg=$(awk -F'\t' '
    { rounds++
      f = 0
      if (match($0, /fails=[0-9]+/)) { v = substr($0, RSTART+6, RLENGTH-6); tf += v; if (v+0 > 0) f = 1 }
      if (match($0, /warns=[0-9]+/)) { v = substr($0, RSTART+6, RLENGTH-6); tw += v }
      if (match($0, /files=[0-9]+/)) { v = substr($0, RSTART+6, RLENGTH-6); tfz += v }
      if (f) violating++
    }
    END { printf "%d %d %d %d %d", rounds, violating, tf, tw, tfz }
  ' "$VIO")
  set -- $agg
  local rounds="$1" violating="$2" tfails="$3" twarns="$4" tfiles="$5"

  # 遵守率 = 1 − 命中轮次/总轮次，保留一位小数
  local rate="n/a"
  if [ "$rounds" -gt 0 ]; then
    rate=$(awk -v v="$violating" -v r="$rounds" 'BEGIN { printf "%.1f", (1 - v/r) * 100 }')
  fi

  if [ "$as_json" -eq 1 ]; then
    # 字段名说清是累计还是均值——之前叫 filesPerRound 却给累计值，读的人会误判
    printf '{"rounds":%s,"violating":%s,"rate":%s,"totalFails":%s,"totalWarns":%s,"filesTotal":%s,"filesAvg":%s}\n' \
      "$rounds" "$violating" "$rate" "$tfails" "$twarns" "$tfiles" \
      "$( [ "$rounds" -gt 0 ] && awk -v f="$tfiles" -v r="$rounds" 'BEGIN{printf "%.1f", f/r}' || echo 0 )"
    return 0
  fi

  echo "compliance · 遵守率（ADR 0009 · 口径见设计稿 §11.2）"
  echo "  记录轮次        : $rounds"
  echo "  其中有命中的轮次 : $violating"
  echo "  遵守率          : ${rate}%"
  echo "  累计 ❌ / ⚠️    : $tfails / $twarns"
  echo "  平均每轮改动文件 : $( [ "$rounds" -gt 0 ] && awk -v f="$tfiles" -v r="$rounds" 'BEGIN{printf "%.1f", f/r}' || echo 0 ) 个"
  if [ -s "$LOAD" ]; then
    echo "  ── 单轮加载量（load-estimate.sh 口径）"
    awk -F'\t' '{ if (match($0, /bytes=[0-9]+/)) { v=substr($0,RSTART+6,RLENGTH-6); s+=v; n++; if (v>max) max=v } }
         END { if (n>0) printf "    已记录 %d 轮 · 平均 %d 字节 · 峰值 %d 字节（预算 %s）\n", n, s/n, max, "'"${BYTES_SESSION:-15000}"'" }' "$LOAD"
  fi
  echo
  echo "  ⚠️ 读数字之前先读这三条："
  echo "     1. 遵守率低**先查规则是否可遵守**（§2 原则 4），不是先怪 AI"
  echo "     2. 它只量「提交时的合规」，没提交的工作不计入"
  echo "     3. 没有基线就没有意义——第一次的数字别当成绩"
}

# ── reset：清空 ─────────────────────────────────────────────────
reset() {
  local n=0
  [ -f "$VIO" ] && n=$(wc -l < "$VIO" | tr -d '[:space:]') && : > "$VIO"
  [ -f "$LOAD" ] && : > "$LOAD"
  echo "compliance · 已清空 ${n} 条记录（换基线时用；记下清空日期，§11.2 的口径要求可追溯）"
}

case "$cmd" in
  record) record "$@" ;;
  report) report "$@" ;;
  reset)  reset ;;
  *)      echo "用法: bash keel/checks/compliance.sh {record|report [--json]|reset}"; exit 1 ;;
esac
exit 0
