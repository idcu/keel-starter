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
  local fails=0 warns=0 files=0 checked=1 md=0 baseline=0
  while [ $# -gt 0 ]; do
    case "$1" in
      --fails) fails="${2:-0}"; shift 2 ;;
      --warns) warns="${2:-0}"; shift 2 ;;
      --files) files="${2:-0}"; shift 2 ;;
      --checked) checked="${2:-1}"; shift 2 ;;
      --md) md="${2:-0}"; shift 2 ;;
      --baseline) baseline="${2:-0}"; shift 2 ;;
      *) shift ;;
    esac
  done
  [ -f "$VIO" ] || : > "$VIO"
  local ts commit
  ts=$(date '+%Y-%m-%dT%H:%M:%S%z')
  commit=$(git rev-parse --short HEAD 2>/dev/null || echo "-")
  # 只记数字与事实，不记 AI 的任何自述。
  # checked=0 表示"这轮没跑 lint"（没改 keel 的 md）——分母里有它，
  # 分子里没有它，于是"没被检查"不会伪装成"检查通过"（v3.3.2 修正）。
  # baseline=1 表示"这是初始化/换基线，不算违反轮次"（install.sh 装完会记一条）。
  # 否则新用户第一次看报告，会被 50 个模板文件的初始化噪声吓到。
  printf '%s\tcommit=%s\tchecked=%s\tfails=%s\twarns=%s\tfiles=%s\tmd=%s\tbaseline=%s\n' \
    "$ts" "$commit" "$checked" "$fails" "$warns" "$files" "$md" "$baseline" >> "$VIO"
}

# ── report：出报告 ──────────────────────────────────────────────
report() {
  local as_json=0
  for a in "$@"; do [ "$a" = "--json" ] && as_json=1; done

  # ── 放行后被回滚的提交（v3.3.1 起纳入分子）──────────────────
  # 为什么必须算：lint 说"通过"、提交成功，但后来被 revert 了——
  # **那才是真正的"不遵守"**，而且是 lint 自己看不见的那一类。
  # 只看 lint 命中会把"事后被推翻的提交"算成遵守，虚高。
  #
  # 匹配 `^Revert "` 是精确的 git 自动生成格式；**不用 `-i --grep=revert`**——
  # 实测后者会把"实现 revert 按钮的功能"这类普通提交误计进去。
  local reverts=0
  if git rev-parse --git-dir >/dev/null 2>&1; then
    reverts=$(git log --oneline --grep='^Revert "' 2>/dev/null | wc -l | tr -d '[:space:]')
  fi

  if [ ! -s "$VIO" ]; then
    if [ "$as_json" -eq 1 ]; then
      printf '{"rounds":0,"violating":0,"reverted":%s,"rate":null,"note":"no data"}\n' "$reverts"
    else
      echo "compliance · 还没有任何记录"
      echo "   记录由 pre-commit 自动写入；先提交一次（哪怕 --no-verify 也会记）再来看。"
      [ "$reverts" -gt 0 ] && echo "   （已发现 $reverts 笔 revert 提交——它们会计入分子）"
    fi
    return 0
  fi

  # 一次 awk 算完：轮次、命中轮次、累计 fails/warns/files
  local agg
  agg=$(awk -F'\t' '
    # baseline 轮次（初始化/换基线）不计入分母——它不是"一次工作"，是"装了个模板"。
    # 写法上刻意用最朴素的 if：早先试过三元表达式和 next+块 两种写法，
    # 都在部分 awk 实现上直接语法报错（且报错信息指向上面那行，看不出真正原因）。
    {
      rbl = match($0, /baseline=1/)
      if (rbl > 0) { baselines++; next }

      rounds++
      # 老记录没有 checked 字段（v3.3.1 及之前）——按"已检查"处理，保持连续性
      ck = 1
      r = match($0, /checked=[01]/)
      if (r > 0) ck = substr($0, RSTART + 8, 1) + 0
      if (ck > 0) checked++

      f = 0
      r = match($0, /fails=[0-9]+/)
      if (r > 0) { v = substr($0, RSTART + 6, RLENGTH - 6) + 0; tf += v; if (v > 0) f = 1 }
      r = match($0, /warns=[0-9]+/)
      if (r > 0) { v = substr($0, RSTART + 6, RLENGTH - 6) + 0; tw += v }
      r = match($0, /files=[0-9]+/)
      if (r > 0) { v = substr($0, RSTART + 6, RLENGTH - 6) + 0; tfz += v }

      if (f > 0) violating++
    }
    END { printf "%d %d %d %d %d %d %d", rounds, checked, violating, tf, tw, tfz, baselines + 0 }
  ' "$VIO")
  set -- $agg
  local rounds="$1" checked="$2" violating="$3" tfails="$4" twarns="$5" tfiles="$6" baselines="$7"

  # 遵守率 = 1 − (被拦截的轮次 + 事后被回滚的提交) / 总轮次
  #
  # 分子为什么是"命中轮次 + 回滚数"而不是"命中条数"：
  #   一次提交踩 3 条和踩 1 条，对"这轮守没守规矩"是同一件事；
  #   而"lint 放行、事后被 revert"与"lint 拦截"在**守没守规矩**这件事上也是同一件——
  #   都是这一轮没有产出可接受的结果。放行后回滚甚至更严重：
  #   它先是骗过了门禁，之后才被推翻。
  local viol_total=$((violating + reverts))
  # rate 在 JSON 里必须是合法 null，不能是字符串 "n/a"——否则 jq / node -e 之类
  # 的消费者会解析失败（实测发现：手写 JSON 很容易漏这一点）
  local rate_json="null" rate_txt="—"
  if [ "$rounds" -gt 0 ]; then
    rate_json=$(awk -v v="$viol_total" -v r="$rounds" 'BEGIN { printf "%.1f", (1 - v/r) * 100 }')
    rate_txt="${rate_json}%"
  fi

  # 预算超限率（调研报告 §5.2）：测的是"上下文基座够不够用"，与遵守率正相关
  local over_n=0 over_r=0
  if [ -s "$LOAD" ]; then
    set -- $(awk -F'\t' '
      { n++
        if (match($0, /bytes=[0-9]+/)) { v = substr($0, RSTART+6, RLENGTH-6)+0; s += v; if (v > max) max = v }
        if (match($0, /over=[01]/)) { if (substr($0, RSTART+5, 1) == "1") o++ }
      }
      END { printf "%d %d %d", n+0, o+0, (n>0 ? s/n : 0) }' "$LOAD")
    over_n="$1"; over_r="$2"
  fi

  if [ "$as_json" -eq 1 ]; then
    printf '{"rounds":%s,"checked":%s,"coverage":%s,"violating":%s,"reverted":%s,"violationsTotal":%s,"rate":%s,"totalFails":%s,"totalWarns":%s,"filesTotal":%s,"filesAvg":%s,"loadOverRate":%s}\n' \
      "$rounds" "$checked" \
      "$( [ "$rounds" -gt 0 ] && awk -v c="$checked" -v r="$rounds" 'BEGIN{printf "%.1f", c/r*100}' || echo "null" )" \
      "$violating" "$reverts" "$viol_total" "$rate_json" "$tfails" "$twarns" "$tfiles" \
      "$( [ "$rounds" -gt 0 ] && awk -v f="$tfiles" -v r="$rounds" 'BEGIN{printf "%.1f", f/r}' || echo 0 )" \
      "$( [ "$over_n" -gt 0 ] && awk -v o="$over_r" -v n="$over_n" 'BEGIN{printf "%.1f", o/n*100}' || echo "null" )"
    return 0
  fi

  echo "compliance · 遵守率（ADR 0009 · 口径见设计稿 §11.2）"
  echo "  提交轮次（分母）   : $rounds"
  echo "  ├ 其中跑过 lint    : $checked（覆盖 $( [ "$rounds" -gt 0 ] && awk -v c="$checked" -v r="$rounds" 'BEGIN{printf "%.0f", c/r*100}' || echo 0 )%）"
  echo "  └ 未跑（没改 md）  : $((rounds - checked))  ← 这些不算"通过"，只算"未检查""
  echo "  ├ lint 命中被拦    : $violating"
  echo "  └ 放行后被回滚     : $reverts   ← lint 看不见的那一类"
  echo "  违反合计（分子）   : $viol_total"
  echo "  遵守率             : ${rate_txt}"
  [ "$baselines" -gt 0 ] && echo "  （另有 $baselines 条基线记录已排除：装模板/换基线，不算工作轮次）"
  echo "  累计 ❌ / ⚠️       : $tfails / $twarns"
  echo "  平均每轮改动文件    : $( [ "$rounds" -gt 0 ] && awk -v f="$tfiles" -v r="$rounds" 'BEGIN{printf "%.1f", f/r}' || echo 0 ) 个"
  if [ -s "$LOAD" ]; then
    echo "  ── 单轮加载量（load-estimate.sh 口径 · 预算 ${BYTES_SESSION:-15000}）"
    awk -F'\t' '{ if (match($0, /bytes=[0-9]+/)) { v=substr($0,RSTART+6,RLENGTH-6)+0; s+=v; n++; if (v>max) max=v } }
         END { if (n>0) printf "    已记录 %d 轮 · 平均 %d 字节 · 峰值 %d 字节\n", n, s/n, max }' "$LOAD"
    if [ "$over_n" -gt 0 ]; then
      echo "    超限率 $over_r/$over_n 轮 = $(awk -v o="$over_r" -v n="$over_n" 'BEGIN{printf "%.1f", o/n*100}')%"
    fi
  fi
  echo
  echo "  ⚠️ 读数字之前先读这五条："
  echo "     1. 遵守率低**先查规则是否可遵守**（§2 原则 4），不是先怪 AI"
  echo "     2. 看遵守率**必须同时看覆盖率**：覆盖率低时高分没有意义"
  echo "        （未检查的提交计入分母但不计入分子，会把数字压低而非抬高——"
  echo "         所以真正的风险是「覆盖率低 + 遵守率高」= 大量提交根本没被检查）"
  echo "     3. 回滚数高 → 多半是**门禁放行了不该放的东西**（不是 AI 不听话）"
  echo "     4. 它只量「提交时的合规」，没提交的工作不计入"
  echo "     5. 没有基线就没有意义——第一次的数字别当成绩"
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
