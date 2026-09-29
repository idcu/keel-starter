#!/usr/bin/env bash
# keel-lint.sh —— Keel 一致性校验（v3）
# 用法:  bash keel/checks/keel-lint.sh keel            # 从项目根目录调用
#        bash checks/keel-lint.sh                     # 在 keel/ 内调用（默认 .）
# 退出码: 0 = 通过（含 warn）；1 = 存在 fail；2 = keel 目录不存在
# 口径:  热区 = 全部 md 减去 archive/ 与 NOW-history/；冷区只做死链检查。
# 依赖:  bash 3.2+ / awk / sed / find / tsort（可选）/ git（仅 frozen 检查用）
set -uo pipefail

KEEL_DIR="${1:-.}"; KEEL_DIR="${KEEL_DIR%/}"
[ -d "$KEEL_DIR" ] || { echo "❌ 目录不存在: $KEEL_DIR"; exit 2; }

# ---------- 硬预算默认值（兜底；真源是 checks/budget.env） ----------
MAX_INDEX=100;        BYTES_INDEX=4500
MAX_DOMAIN_INDEX=80;  BYTES_DOMAIN_INDEX=3000
MAX_NOW=60;           BYTES_NOW=2400
MAX_PIT=30;           BYTES_PIT=1200
MAX_DOC=160;          BYTES_DOC=4800
BYTES_FM=600
MAX_LINE=360
MAX_DIR_FILES=20
STALE_DAYS=30
NOW_STALE_DAYS=7
DISTILL_AT=3

# §4.1 门外锚点原文（唯一允许存在于 Keel 之外的一句）
ANCHOR='任何任务开始前，先读 keel/INDEX.md 与其中指向的 NOW.md，并遵守 INDEX.md 里的检索协议。'

fail=0
fail_msg() { echo "❌ $1"; fail=1; }
warn_msg() { echo "⚠️ $1"; }

# ---------- budget.env（唯一真源；缺失即 fail，兜底用上方默认值） ----------
if [ -f "$KEEL_DIR/checks/budget.env" ]; then
  . "$KEEL_DIR/checks/budget.env"
else
  fail_msg "缺预算真源 checks/budget.env（§9.3），已退回内置默认值"
fi

hot_files() { find "$KEEL_DIR" -name '*.md' -not -path '*/archive/*' -not -path '*/NOW-history/*' 2>/dev/null; }
all_files() { find "$KEEL_DIR" -name '*.md' 2>/dev/null; }
rel_of() { printf '%s' "${1#"$KEEL_DIR"/}"; }
# 取首个 --- 块（v3 修正：不再只扫前 12 行，否则字段放后面会被误判为"缺失"）
fm_block() { awk 'NR==1 && $0=="---" { f=1; next } f && $0=="---" { exit } f { print }' "$1" 2>/dev/null; }
fm_end_line() { awk 'NR==1 && $0=="---" { next } /^---$/ { print NR; exit }' "$1" 2>/dev/null; }
# frontmatter 按 YAML 解析：`key: value   # 注释` 里的行内注释必须剥掉
# （§5.2 / §5.3 的模板自带注释，不剥就会把注释当成值的一部分，直接误判值域非法）
# `key: # 注释` 这种"值整个是注释"的写法同样按空值处理（YAML 语义），否则
# 会得到一个假的非空值——例如占位用的 `superseded-by:` 会被误判成"指向不存在的文件"
yaml_val() { sed -E "s/^#.*$//; s/[[:space:]]+#.*$//; s/[[:space:]]+$//"; }
fm_val() { fm_block "$1" | grep -m1 "^$2:" | sed -E "s/^$2:[[:space:]]*//" | yaml_val; }
to_epoch() { date -j -f "%Y-%m-%d" "$1" +%s 2>/dev/null || date -d "$1" +%s 2>/dev/null || true; }

tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
# 用临时文件收集结果：兼容 bash 3.2（case 不能直接出现在 $() 内），也避开管道子 shell 吞掉 fail 计数
deadf="$tmp/dead"; corpus="$tmp/corpus"; longf="$tmp/long"; idxbad="$tmp/idxbad"; edges="$tmp/edges"

echo "keel-lint · $(date '+%Y-%m-%d %H:%M') · 目录=$KEEL_DIR · 热区文档=$(hot_files | wc -l | tr -d '[:space:]')"
echo "── 1. 预算：行数 / 字节 / 单行 / 目录文件数"
while IFS= read -r f; do
  rel=$(rel_of "$f")
  case "$rel" in
    */INDEX.md)          lim=$MAX_DOMAIN_INDEX; blim=$BYTES_DOMAIN_INDEX ;;
    INDEX.md)            lim=$MAX_INDEX;        blim=$BYTES_INDEX ;;
    NOW*.md|*/NOW*.md)   lim=$MAX_NOW;          blim=$BYTES_NOW ;;
    pitfalls/*)          lim=$MAX_PIT;          blim=$BYTES_PIT ;;
    *)                   lim=$MAX_DOC;          blim=$BYTES_DOC ;;
  esac
  n=$(wc -l < "$f" | tr -d '[:space:]')
  b=$(wc -c < "$f" | tr -d '[:space:]')
  [ "$n" -gt "$lim" ]  && fail_msg "超行数 ${n}>${lim}: $rel"
  [ "$b" -gt "$blim" ] && fail_msg "超字节 ${b}>${blim}: $rel"
done < <(hot_files)

# 单行上限：LC_ALL=C 保证 awk 的 length() 按字节而非字符计
while IFS= read -r f; do
  LC_ALL=C awk -v R="$(rel_of "$f")" -v L="$MAX_LINE" \
    'length($0) > L { printf "❌ 单行超限 %d>%d 字节: %s:%d\n", length($0), L, R, NR }' "$f"
done < <(hot_files) > "$longf"
if [ -s "$longf" ]; then sed -n '1,10p' "$longf"; fail=1; fi

while IFS= read -r d; do
  case "$d" in */archive|*/archive/*|*/NOW-history|*/NOW-history/*) continue ;; esac
  c=$(find "$d" -maxdepth 1 -type f | wc -l | tr -d '[:space:]')
  [ "$c" -gt "$MAX_DIR_FILES" ] && fail_msg "目录文件超限 ${c}>${MAX_DIR_FILES}: $(rel_of "$d")/"
done < <(find "$KEEL_DIR" -type d 2>/dev/null)

echo "── 2. frontmatter：存在性 / 字段 / 行数 / 字节"
while IFS= read -r f; do
  base=$(basename "$f")
  case "$base" in _template*) continue ;; esac
  rel=$(rel_of "$f")
  if ! head -1 "$f" | grep -q '^---$'; then fail_msg "缺 frontmatter: $rel"; continue; fi
  end=$(fm_end_line "$f")
  if [ -z "$end" ]; then fail_msg "frontmatter 未闭合: $rel"; continue; fi
  nl=$((end - 2))
  [ "$nl" -gt 10 ] && fail_msg "frontmatter 超行数 ${nl}>10: $rel"
  nb=$(sed -n "1,${end}p" "$f" | wc -c | tr -d '[:space:]')
  [ "$nb" -gt "$BYTES_FM" ] && fail_msg "frontmatter 超字节 ${nb}>${BYTES_FM}: $rel"
  fm=$(fm_block "$f")
  for k in scope status last-verified keywords; do
    printf '%s\n' "$fm" | grep -q "^$k:" || fail_msg "frontmatter 缺 $k: $rel"
  done
  case "$rel" in
    */INDEX.md) ;;   # 域索引只查基础字段
    skills/*)   printf '%s\n' "$fm" | grep -q '^trigger:'  || fail_msg "skill 缺 trigger: $rel" ;;
    pitfalls/*) printf '%s\n' "$fm" | grep -q '^severity:' || fail_msg "坑条目缺 severity: $rel"
                printf '%s\n' "$fm" | grep -q '^triggers:' || fail_msg "坑条目缺 triggers: $rel" ;;
  esac
  case "$rel" in
    INDEX.md)   printf '%s\n' "$fm" | grep -q '^keel-version:'  || fail_msg "根 INDEX 缺 keel-version: $rel"
                printf '%s\n' "$fm" | grep -q '^project-state:' || fail_msg "根 INDEX 缺 project-state: $rel" ;;
  esac
done < <(hot_files)

echo "── 3. 值域与格式（status / severity / keywords / last-verified / triggers）"
while IFS= read -r f; do
  base=$(basename "$f")
  case "$base" in _template*) continue ;; esac
  rel=$(rel_of "$f")
  fm=$(fm_block "$f"); [ -z "$fm" ] && continue
  st=$(printf '%s\n' "$fm" | grep -m1 '^status:' | sed -E 's/^status:[[:space:]]*//' | yaml_val)
  case "${st:-}" in
    active|distilled|archived|"") ;;
    *) fail_msg "status 值域非法（${st}）: $rel" ;;
  esac
  lv=$(printf '%s\n' "$fm" | grep -m1 '^last-verified:' | sed -E 's/^last-verified:[[:space:]]*//' | yaml_val)
  if [ -n "${lv:-}" ]; then
    case "$lv" in
      [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]) ;;
      *) fail_msg "last-verified 非 YYYY-MM-DD（${lv}）: $rel" ;;
    esac
  fi
  kw=$(printf '%s\n' "$fm" | grep -m1 '^keywords:' | sed -E 's/^keywords:[[:space:]]*//' | yaml_val)
  case "${kw:-}" in ""|"[]"|"[ ]") fail_msg "keywords 为空: $rel" ;; esac
  case "$rel" in
    pitfalls/*)
      sv=$(printf '%s\n' "$fm" | grep -m1 '^severity:' | sed -E 's/^severity:[[:space:]]*//' | yaml_val)
      case "${sv:-}" in
        P0|P1|P2|P3|"") ;;
        *) fail_msg "severity 值域非法（${sv}）: $rel" ;;
      esac
      tg=$(printf '%s\n' "$fm" | grep -m1 '^triggers:' | sed -E 's/^triggers:[[:space:]]*//' | yaml_val)
      case "${tg:-}" in
        ''|*[!0-9]*) [ -n "${tg:-}" ] && fail_msg "triggers 非数字（${tg}）: $rel" ;;
      esac
      ;;
  esac
done < <(hot_files)

echo "── 4. 命名（kebab-case / 热区禁日期）"
while IFS= read -r f; do
  base=$(basename "$f"); rel=$(rel_of "$f")
  # 固定名豁免：根级入口/地图/宪法/术语/NOW 由 §3.2 定义，不受 kebab-case 约束
  case "$base" in
    _template*|INDEX.md|CONSTITUTION.md|ARCHITECTURE.md|GLOSSARY.md|NOW.md|NOW-*.md) continue ;;
  esac
  case "$base" in *[A-Z]*)     fail_msg "命名含大写（应 kebab-case）: $rel" ;; esac
  case "$base" in *"_"*|*" "*) fail_msg "命名含下划线/空格（应 kebab-case）: $rel" ;; esac
  case "$base" in *[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*) fail_msg "热区文件名含日期: $rel" ;; esac
done < <(hot_files)

echo "── 5. 域索引：纯表格 / 坑条目登记"
# 5a. 任何域索引（*/INDEX.md）只允许表格行；根 INDEX.md 例外（它是唯一入口，见 §5.1）
: > "$idxbad"
while IFS= read -r x; do
  xrel=$(rel_of "$x")
  case "$xrel" in */INDEX.md) ;; *) continue ;; esac
  awk -v R="$xrel" '
    NR==1 && $0=="---" { f=1; next }
    f==1 && $0=="---" { f=0; next }
    f==1 { next }
    $0 ~ /^[[:space:]]*$/ { next }
    $0 !~ /^\|/ { printf "❌ 域索引含非表格正文: %s 第%d行: %s\n", R, NR, substr($0,1,30) }
  ' "$x"
done < <(hot_files) >> "$idxbad"
if [ -s "$idxbad" ]; then sed -n '1,6p' "$idxbad"; fail=1; fi
# 5b. 坑条目必须登记进 pitfalls/INDEX.md
if [ -f "$KEEL_DIR/pitfalls/INDEX.md" ]; then
  while IFS= read -r p; do
    b=$(basename "$p")
    case "$b" in INDEX.md|_template*) continue ;; esac
    grep -qF "$b" "$KEEL_DIR/pitfalls/INDEX.md" || fail_msg "坑条目未登记进 pitfalls/INDEX.md: $(rel_of "$p")"
  done < <(find "$KEEL_DIR/pitfalls" -name '*.md' 2>/dev/null)
else
  fail_msg "缺 pitfalls/INDEX.md"
fi

echo "── 6. 引用图环检测（md → md；§3.1 禁止循环引用，路由枢纽 INDEX.md 除外）"
: > "$edges"
while IFS= read -r f; do
  from=$(basename "$f")
  [ "$from" = "INDEX.md" ] && continue
  {
    grep -oE '\]\([^)]+\)' "$f" 2>/dev/null | sed -E 's/^\]\(([^) ]+).*/\1/'
    grep -oE '@[A-Za-z0-9_./-]+\.md' "$f" 2>/dev/null | tr -d '@'
  } | sort -u | while IFS= read -r link; do
    case "$link" in http*|mailto:*|"") continue ;; esac
    t="${link%%#*}"
    case "$t" in *.md) ;; *) continue ;; esac
    to=$(basename "$t")
    # 索引是路由枢纽（人人都指向它、它也指向人人），把它当普通节点必然误报
    [ "$to" = "INDEX.md" ] && continue
    [ "$from" = "$to" ] && continue
    printf '%s %s\n' "$from" "$to"
  done
done < <(hot_files) >> "$edges"
sort -u "$edges" -o "$edges"
if [ -s "$edges" ]; then
  if command -v tsort >/dev/null 2>&1; then
    tsort "$edges" >/dev/null 2>"$tmp/tsort.err"; tsort_rc=$?
    # 注意：BSD/macOS 的 tsort 遇环仍返回 0，只把 "cycle in data" 写到 stderr；
    # GNU tsort 返回 1。所以"退出码非 0"和"stderr 非空"两个条件要一起看。
    if [ "$tsort_rc" -ne 0 ] || [ -s "$tmp/tsort.err" ]; then
      fail_msg "引用存在环（§3.1 禁止循环引用）: $(head -1 "$tmp/tsort.err")"
    fi
  else
    warn_msg "环境无 tsort，跳过循环引用检查"
  fi
fi

echo "── 7. 必读文件与点火锚点"
for need in INDEX.md CONSTITUTION.md; do
  [ -f "$KEEL_DIR/$need" ] || fail_msg "缺必读文件: $need"
done
[ "$(find "$KEEL_DIR" -maxdepth 1 -name 'NOW*.md' | wc -l | tr -d '[:space:]')" -eq 0 ] && fail_msg "缺必读文件: NOW*.md"
anchor_ok=0
for cand in CLAUDE.md AGENTS.md .cursorrules .cursor/rules/keel.mdc; do
  for pfx in "$KEEL_DIR/.." "$KEEL_DIR"; do
    [ -f "$pfx/$cand" ] || continue
    grep -qF "$ANCHOR" "$pfx/$cand" && anchor_ok=1
  done
done
[ "$anchor_ok" -eq 1 ] || fail_msg "点火锚点缺失或与 §4.1 原文不一致（查 CLAUDE.md / AGENTS.md / .cursorrules / .cursor/rules）"

echo "── 8. 死链（@路径 与 markdown 链接，相对所在文件目录）"
while IFS= read -r f; do
  dir=$(dirname "$f")
  {
    grep -oE '\]\([^)]+\)' "$f" 2>/dev/null | sed -E 's/^\]\(([^) ]+).*/\1/'
    grep -oE '@[A-Za-z0-9_./-]+\.md' "$f" 2>/dev/null | tr -d '@'
  } | sort -u | while IFS= read -r link; do
    case "$link" in http*|mailto:*|"") continue ;; esac
    t="${link%%#*}"; [ -z "$t" ] && continue
    [ -e "$dir/$t" ] || echo "❌ 死链: $t  (见 $(rel_of "$f"))"
  done
done < <(all_files) > "$deadf"
if [ -s "$deadf" ]; then cat "$deadf"; fail=1; fi

echo "── 9. 孤儿（热区文档未被任何热区文档引用；INDEX/_template 豁免）"
while IFS= read -r g; do cat "$g" >>"$corpus" 2>/dev/null; printf '\n' >>"$corpus"; done < <(hot_files)
while IFS= read -r f; do
  base=$(basename "$f")
  case "$base" in INDEX.md|_template*) continue ;; esac
  grep -qF "$base" "$corpus" || fail_msg "孤儿（未被任何热区文档引用）: $(rel_of "$f")"
done < <(hot_files)

echo "── 10. 陈旧（last-verified / NOW updated；豁免类目见 §9.4）"
today=$(date +%s)
while IFS= read -r f; do
  rel=$(rel_of "$f")
  case "$(basename "$f")" in _template*) continue ;; esac
  case "$rel" in decisions/*) continue ;; esac            # ADR 定稿即不可变，见 §9.4
  [ "$(fm_val "$f" stale-check)" = "off" ] && continue     # 逃生口，需在 decisions/ 留理由
  d=$(fm_val "$f" last-verified)
  if [ -n "$d" ]; then
    e=$(to_epoch "$d")
    if [ -n "$e" ]; then
      age=$(( (today - e) / 86400 ))
      [ "$age" -gt "$STALE_DAYS" ] && warn_msg "stale(${age}d): $rel"
    else
      warn_msg "last-verified 无法解析: $rel ($d)"
    fi
  fi
  case "$rel" in NOW*.md|*/NOW*.md)
    u=$(fm_val "$f" updated)
    if [ -z "$u" ]; then fail_msg "NOW 缺 updated: $rel"
    else
      e=$(to_epoch "$u")
      [ -n "$e" ] && { age=$(( (today - e) / 86400 )); [ "$age" -gt "$NOW_STALE_DAYS" ] && warn_msg "NOW 已 ${age}d 未更新: $rel"; }
    fi ;;
  esac
done < <(hot_files)

echo "── 11. 坑条目（三段式 + 蒸馏阈值）"
while IFS= read -r f; do
  rel=$(rel_of "$f")
  case "$rel" in pitfalls/*) ;; *) continue ;; esac
  case "$(basename "$f")" in INDEX.md|_template*) continue ;; esac
  for h in "## 症状" "## 根因" "## 正解"; do
    grep -qF -- "$h" "$f" || fail_msg "坑条目缺失【${h}】: $rel"
  done
  t=$(fm_val "$f" triggers)
  case "${t:-0}" in
    ''|*[!0-9]*) [ -n "${t:-}" ] && warn_msg "triggers 非数字: $rel" ;;
    *) [ "${t:-0}" -ge "$DISTILL_AT" ] && warn_msg "待蒸馏（triggers=${t} ≥ ${DISTILL_AT}）: $rel" ;;
  esac
done < <(hot_files)

echo "── 12. 状态机（frozen 契约冻结 / 例外计数）"
IDX="$KEEL_DIR/INDEX.md"
if [ -f "$IDX" ]; then
  ps=$(fm_val "$IDX" project-state)
  case "${ps:-}" in
    frozen)
      if command -v git >/dev/null 2>&1 && git -C "$KEEL_DIR" rev-parse --git-dir >/dev/null 2>&1; then
        added=$(git -C "$KEEL_DIR" log --since="$(date '+%Y-%m-01')" --diff-filter=A --name-only --pretty=format: 2>/dev/null | grep -E '(^|/)contracts/' | grep -v '/_template' | sort -u)
        [ -n "$added" ] && fail_msg "frozen 期新增契约文件（§5.2 禁止）: $(printf '%s' "$added" | tr '\n' ' ')"
      fi ;;
    exploring|architecture-locked|building) ;;
    "") fail_msg "project-state 缺失或为空: INDEX.md" ;;
    *)  fail_msg "project-state 值域非法（${ps}）: INDEX.md" ;;
  esac
fi
if [ -d "$KEEL_DIR/decisions" ]; then
  mon=$(date '+%Y-%m'); exc=0
  while IFS= read -r d; do
    case "$(basename "$d")" in _template*) continue ;; esac   # 模板不是真实记录（§3.4 豁免）
    [ "$(fm_val "$d" type)" = "exception" ] || continue
    made=$(fm_val "$d" created)
    if [ -z "${made:-}" ]; then fail_msg "例外决策缺 created 字段: $(rel_of "$d")"; continue; fi
    case "$made" in "$mon"*) exc=$((exc + 1)) ;; esac
  done < <(find "$KEEL_DIR/decisions" -name '*.md' 2>/dev/null)
  [ "$exc" -gt 2 ] && fail_msg "本月例外决策 ${exc}>2，强制退回 building（§5.2）"
fi
# 取代关系：superseded-by 必须指向存在的文件（ADR 靠"被谁取代"表达时效，而非 last-verified）
while IFS= read -r d; do
  case "$(basename "$d")" in _template*) continue ;; esac     # 模板里的占位值不算数
  sb=$(fm_val "$d" superseded-by)
  [ -n "${sb:-}" ] || continue
  [ -e "$(dirname "$d")/$sb" ] || fail_msg "superseded-by 指向不存在的文件（${sb}）: $(rel_of "$d")"
done < <(find "$KEEL_DIR/decisions" -name '*.md' 2>/dev/null)

echo "──"
if [ "$fail" -eq 0 ]; then echo "✅ keel-lint 通过"; else echo "❌ keel-lint 失败（见上方 ❌ 项）"; fi
exit "$fail"
