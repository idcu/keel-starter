#!/usr/bin/env bash
# keel-upgrade.sh —— 已接入仓库的 keel 增量升级（DESIGN.md §12.3 / ADR 0020）
#
# 用法:
#   bash keel/checks/keel-upgrade.sh [--target <项目根>] [--to vX.Y.Z]
#                                    [--from <模板目录>] [--dry-run] [--force]
#                                    [--no-rollback] [--skip-test-lint]
#   bash keel/checks/keel-upgrade.sh --rollback [备份目录]
#   bash keel/checks/keel-upgrade.sh --regen-manifest <keel目录>   # 发布方专用
#   bash keel/checks/keel-upgrade.sh --check-manifest <keel目录>   # 发布方 / CI
#
# 退出码:
#   0 = 升级完成 / 已是目标版本（无需升级）/ 回滚完成 / manifest 一致
#   1 = 升级前门禁未通过（未改动任何文件）/ manifest 与实际文件不一致
#   2 = 用法 / 环境 / 模板校验错误
#   3 = 升级后门禁失败，已自动回滚
#   4 = 升级后门禁失败，未回滚（--no-rollback）
#
# 与 install.sh 的分工（ADR 0020）：install.sh 负责**新建**（全量复制），
# 本脚本负责**升级**（按 manifest.tsv 分类增量合并）。旧版（≤3.5.0）没有本脚本，
# 引导方式就是重跑 install.sh——它会把新模板里的本引擎拉起来。
#
# 分类真源 = 模板里的 checks/manifest.tsv（本脚本不含任何文件名字面量）：
#   kernel   ── 内核工具链，按版本覆盖；本地改过的另存到备份目录并告警
#   merge    ── 只改 INDEX.md 的 keel-version 行；路由表 / project-state 保留
#   preserve ── 采用方自定义，一律不动
#   additive ── 新增结构文件：**父目录已存在**且文件缺失时才补（不复活已裁剪的层）
#
# 备份策略：整目录 cp -R 到 <项目根>/.keel-backup/<from>-to-<to>-<时间>/（保留最近 3 份）。
# 为什么不用 git 还原：采用方工作区常有未提交的自定义，git checkout 会一起吞掉；
# 文件备份在有无 VCS、是否脏工作区下都成立，且 restroll.sh 一条命令可回滚。
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_DEFAULT="https://gitee.com/idcu/keel-starter.git"
BACKUP_KEEP=3

TARGET=""; TO=""; FROM=""; DRY=0; FORCE=0; NO_ROLLBACK=0; SKIP_TL=0
REGEN=""; CHECK=""; RB=""; RB_SET=0

usage() {
  sed -n '3,20p' "$0" | sed 's/^# \{0,1\}//'
}

die() { echo "❌ $2"; exit "$1"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --target) [ $# -ge 2 ] || die 2 "--target 后面要跟目录"; TARGET="$2"; shift 2 ;;
    --target=*) TARGET="${1#--target=}"; shift ;;
    --to) [ $# -ge 2 ] || die 2 "--to 后面要跟版本号"; TO="$2"; shift 2 ;;
    --to=*) TO="${1#--to=}"; shift ;;
    --from) [ $# -ge 2 ] || die 2 "--from 后面要跟模板目录"; FROM="$2"; shift 2 ;;
    --from=*) FROM="${1#--from=}"; shift ;;
    --dry-run) DRY=1; shift ;;
    --force) FORCE=1; shift ;;
    --no-rollback) NO_ROLLBACK=1; shift ;;
    --skip-test-lint) SKIP_TL=1; shift ;;
    --regen-manifest) [ $# -ge 2 ] || die 2 "--regen-manifest 后面要跟 keel 目录"; REGEN="$2"; shift 2 ;;
    --check-manifest) [ $# -ge 2 ] || die 2 "--check-manifest 后面要跟 keel 目录"; CHECK="$2"; shift 2 ;;
    --check-manifest=*) CHECK="${1#--check-manifest=}"; shift ;;
    --rollback) RB_SET=1; shift; [ $# -gt 0 ] && case "$1" in -*) ;; *) RB="$1"; shift ;; esac ;;
    -h|--help) usage; exit 0 ;;
    -*) die 2 "未知参数: $1" ;;
    *) [ -z "$TARGET" ] || die 2 "只能给一个项目根（多了: $1）"; TARGET="$1"; shift ;;
  esac
done

# ---------- sha256（macOS 用 shasum，Linux 用 sha256sum，兜底 openssl）----------
sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'
  elif command -v openssl >/dev/null 2>&1; then openssl dgst -sha256 "$1" | sed 's/.*= *//'
  else echo "__NO_SHA256__"; fi
}
command -v sha256sum >/dev/null 2>&1 || command -v shasum >/dev/null 2>&1 \
  || command -v openssl >/dev/null 2>&1 || die 2 "需要 sha256sum / shasum / openssl 之一（校验模板完整性）"

# 权限位：macOS 的 stat 是 BSD 语法（-f %Lp），Linux 是 GNU（-c %a）
file_mode() {
  if stat -c %a "$1" >/dev/null 2>&1; then stat -c %a "$1" 2>/dev/null
  else stat -f %Lp "$1" 2>/dev/null; fi
}

read_version() { sed -n 's/^keel-version:[[:space:]]*\([^[:space:]]*\).*/\1/p' "$1" 2>/dev/null | head -1; }

# semver: 返回 0 表示 $1 > $2（只比 major.minor.patch 数字部分）
ver_gt() {
  _a=${1%%-*}; _b=${2%%-*}
  _i=1
  while [ "$_i" -le 3 ]; do
    _x=$(printf '%s' "$_a" | cut -d. -f"$_i"); _y=$(printf '%s' "$_b" | cut -d. -f"$_i")
    [ -n "$_x" ] || _x=0; [ -n "$_y" ] || _y=0
    [ "$_x" -gt "$_y" ] && return 0
    [ "$_x" -lt "$_y" ] && return 1
    _i=$((_i + 1))
  done
  return 1
}

# ---------- --regen-manifest（发布方：改过内核文件后重算校验和）----------
if [ -n "$REGEN" ]; then
  K=$(cd "$REGEN" && pwd) || die 2 "目录不存在: $REGEN"
  M="$K/checks/manifest.tsv"
  [ -f "$M" ] || die 2 "缺 ${M}（先手工建立分类清单，本脚本不臆造分类）"
  V=$(read_version "$K/INDEX.md"); [ -n "$V" ] || die 2 "读不到 $K/INDEX.md 的 keel-version"
  tmpm=$(mktemp); trap 'rm -f "$tmpm"' EXIT
  printf '# keel-manifest v1 version=%s generated=%s\n' "$V" "$(date +%Y-%m-%d)" > "$tmpm"
  printf '# 分类: kernel(覆盖) | merge(只改版本行) | preserve(不动) | additive(父目录在才补)\n' >> "$tmpm"
  printf '# 字段: 分类<TAB>相对路径<TAB>权限(可空)<TAB>sha256(仅 kernel)\n' >> "$tmpm"
  stale=0
  while IFS= read -r line; do
    case "$line" in ''|'#'*) continue ;; esac
    cat=$(printf '%s' "$line" | cut -f1)
    rel=$(printf '%s' "$line" | cut -f2)
    mode=$(printf '%s' "$line" | cut -f3)
    if [ -f "$K/$rel" ]; then mode=$(file_mode "$K/$rel"); fi   # 权限以磁盘为准
    if [ "$cat" = "kernel" ]; then
      [ -f "$K/$rel" ] || { echo "⚠️  kernel 行指向不存在的文件: $rel"; stale=1; continue; }
      h=$(sha256_of "$K/$rel")
      printf 'kernel\t%s\t%s\t%s\n' "$rel" "$mode" "$h" >> "$tmpm"
    else
      printf '%s\t%s\t%s\t\n' "$cat" "$rel" "$mode" >> "$tmpm"
    fi
  done < "$M"
  # 安全网：checks/ 下未登记的文件提示出来（不臆造分类，只提醒）
  find "$K/checks" -type f ! -name '*.log' ! -name 'manifest.tsv' 2>/dev/null | sed "s#$K/##" | sort | while IFS= read -r rel; do
    grep -q "^[^#].*	$rel	" "$M" || echo "⚠️  未登记在 manifest 的文件: ${rel}（按需加 kernel/additive/preserve 行）"
  done
  # 先判再落盘：否则 kernel 行指向缺失文件时会把坏清单写下去，等于"拒绝发布"却留下残缺清单
  [ "$stale" -eq 0 ] || { echo "❌ 有 kernel 行指向缺失文件，拒绝发布（原清单未改动）"; exit 2; }
  mv "$tmpm" "$M"
  echo "✅ 已重算 manifest: ${M}（version=${V}）"
  exit 0
fi

# ---------- --check-manifest（发布方 / CI：清单与实际文件是否一致）----------
# 为什么要有它：改过 kernel 文件却忘重算 sha256，升级时才会在采用方机器上报
# 「模板文件校验和不符」——那是**升级失败**，不是发布前能发现的问题。
if [ -n "$CHECK" ]; then
  K=$(cd "$CHECK" && pwd) || die 2 "目录不存在: $CHECK"
  M="$K/checks/manifest.tsv"
  [ -f "$M" ] || die 2 "缺 ${M}"
  bad=0; n=0
  hv=$(sed -n '1s/.*version=\([^ ]*\).*/\1/p' "$M" | head -1)
  iv=$(read_version "$K/INDEX.md")
  if [ -n "$hv" ] && [ -n "$iv" ] && [ "$hv" != "$iv" ]; then
    echo "❌ 版本漂移: manifest 头 version=${hv}，INDEX 是 ${iv}（跑 --regen-manifest 重算）"
    bad=$((bad + 1))
  fi
  while IFS= read -r line; do
    case "$line" in ''|'#'*) continue ;; esac
    cat=$(printf '%s' "$line" | cut -f1)
    rel=$(printf '%s' "$line" | cut -f2)
    mode=$(printf '%s' "$line" | cut -f3)
    want=$(printf '%s' "$line" | cut -f4)
    n=$((n + 1))
    f="$K/$rel"
    case "$cat" in
      kernel)
        if [ ! -f "$f" ]; then
          echo "❌ 文件缺失: ${rel}"; bad=$((bad + 1)); continue
        fi
        got=$(sha256_of "$f")
        if [ "$got" != "$want" ]; then
          echo "❌ 哈希漂移: ${rel}"
          echo "   期望 ${want}"
          echo "   实际 ${got}"
          bad=$((bad + 1)); continue
        fi ;;
      additive) [ -f "$f" ] || continue ;;
      *) continue ;;
    esac
    if [ -n "$mode" ] && [ -f "$f" ]; then
      gotm=$(file_mode "$f")
      case "$gotm" in ''|*[!0-9]*) gotm="" ;; esac
      while [ -n "$gotm" ]; do case "$gotm" in 0*) gotm=${gotm#0} ;; *) break ;; esac; done
      if [ -n "$gotm" ] && [ "$gotm" != "$mode" ]; then
        echo "❌ 权限不符: ${rel}（期望 ${mode} / 实际 ${gotm}）"; bad=$((bad + 1))
      fi
    fi
  done < "$M"
  # 反向：checks/ 下有文件没登记——等于它永远不会被分发（新内核文件最容易这样丢）
  find "$K/checks" -type f ! -name '*.log' ! -name 'manifest.tsv' 2>/dev/null \
    | sed "s#${K}/##" | sort | while IFS= read -r rel; do
      grep -q "^[^#].*	${rel}	" "$M" || echo "⚠️  未登记的文件: ${rel}（不会被分发；确认后加 manifest 行）"
    done
  if [ "$bad" -eq 0 ]; then
    echo "✅ manifest 与实际文件一致（${n} 行）"
    exit 0
  fi
  echo "❌ manifest 与实际文件不一致：${bad} 项（发布方跑 --regen-manifest 重算）"
  exit 1
fi

# ---------- --rollback ----------
if [ "$RB_SET" -eq 1 ]; then
  [ -n "$TARGET" ] || TARGET=$(pwd)
  TARGET=$(cd "$TARGET" && pwd) || die 2 "目录不存在"
  B="$RB"
  if [ -z "$B" ]; then
    B=$(ls -1dt "$TARGET"/.keel-backup/*/ 2>/dev/null | head -1 | sed 's#/$##')
    [ -n "$B" ] || die 2 "找不到任何备份（$TARGET/.keel-backup）"
  fi
  [ -d "$B/keel" ] || die 2 "备份目录里没有 keel/: $B"
  rm -rf "$TARGET/keel" && cp -R "$B/keel" "$TARGET/keel" \
    || die 2 "回滚复制失败（原目录可能被占用）"
  echo "✅ 已回滚到备份: $B"
  exit 0
fi

# ---------- 定位目标仓 ----------
[ -n "$TARGET" ] || TARGET=$(pwd)
TARGET=$(cd "$TARGET" 2>/dev/null && pwd) || die 2 "目录不存在"
[ -f "$TARGET/keel/INDEX.md" ] || die 2 "目标不是已接入 keel 的仓库（缺 keel/INDEX.md）: $TARGET"
CUR=$(read_version "$TARGET/keel/INDEX.md")
[ -n "$CUR" ] || die 2 "读不到当前 keel-version: $TARGET/keel/INDEX.md"
OLD_MANIFEST="$TARGET/keel/checks/manifest.tsv"
[ -f "$OLD_MANIFEST" ] || OLD_MANIFEST=""

# ---------- 取模板 ----------
tmp=""
cleanup() { [ -n "$tmp" ] && rm -rf "$tmp"; }
trap cleanup EXIT

SRC=""
if [ -n "$FROM" ]; then
  SRC=$(cd "$FROM" 2>/dev/null && pwd) || die 2 "模板目录不存在: $FROM"
else
  command -v git >/dev/null 2>&1 || die 2 "未指定 --from 时需要 git（从 $REPO_DEFAULT 取模板）"
  tmp=$(mktemp -d)
  ref="${TO:-main}"
  git clone --depth 1 --branch "$ref" "$REPO_DEFAULT" "$tmp/starter" 2>/dev/null \
    || die 2 "拉取模板失败: $REPO_DEFAULT @ ${ref}（用 --from <本地模板目录> 可离线升级）"
  SRC="$tmp/starter"
fi
SRC_KEEL="$SRC/keel"
[ -d "$SRC_KEEL" ] || SRC_KEEL="$SRC"          # --from 指向 keel/ 目录本身也允许
[ -f "$SRC_KEEL/checks/manifest.tsv" ] || die 2 "模板缺 checks/manifest.tsv（不是 ≥3.6 的模板；旧模板请先重跑 install.sh 引导）"
TOV=$(read_version "$SRC_KEEL/INDEX.md")
[ -n "$TOV" ] || die 2 "模板缺 keel-version: $SRC_KEEL/INDEX.md"
[ -z "$TO" ] || [ "$TO" = "v$TOV" ] || [ "$TO" = "$TOV" ] || \
  echo "⚠️  --to=$TO 但模板实际版本是 ${TOV}（以模板为准）"

echo "keel-upgrade · 目标=$TARGET · $CUR → $TOV · 模式=$([ "$DRY" -eq 1 ] && echo dry-run || echo apply)"

if [ "$CUR" = "$TOV" ] && [ "$FORCE" -eq 0 ]; then
  echo "✅ 已是 v${TOV}，无需升级（--force 可强制重放一次）"
  exit 0
fi
if ver_gt "$CUR" "$TOV"; then
  die 2 "目标版本 $TOV 低于当前 ${CUR}——本工具不支持降级；回滚请用 --rollback"
fi

# ---------- 门禁（升级前）----------
run_lint()   { ( cd "$TARGET" && bash keel/checks/keel-lint.sh keel ); }
run_tl()     { ( cd "$TARGET" && bash keel/checks/test-lint.sh ); }

# 预算门禁 = 协议固定成本（INDEX + 当前 NOW*.md）对 budget.env 的 BYTES_SESSION。
# 为什么不用 load-estimate：它要一个关键词，而"任挑一个词"会把升级报告变成
# 关键词宽窄的随机函数（实测"检索"命中 20567B → 每次都红）。固定成本与本轮
# 读了什么无关，是唯一稳定的预算判据；按需部分仍需用 load-estimate 自查。
run_budget() {
  _b=15000
  if [ -f "$TARGET/keel/checks/budget.env" ]; then
    # shellcheck disable=SC1091
    . "$TARGET/keel/checks/budget.env"
    _b=${BYTES_SESSION:-15000}
  fi
  _sum=0
  for _f in "$TARGET/keel/INDEX.md" "$TARGET"/keel/NOW*.md; do
    [ -f "$_f" ] && _sum=$((_sum + $(wc -c < "$_f" | tr -d ' ')))
  done
  if [ "$_sum" -le "$_b" ]; then echo "固定成本 ${_sum}B ≤ ${_b}B"; return 0; fi
  echo "固定成本 ${_sum}B > ${_b}B"
  return 1
}

gate_report() {
  _who="$1"
  echo "    [${_who}] keel-lint …"
  if run_lint > "$TGT_LOG/lint.$_who" 2>&1; then echo "      ✅ 0 fail"; else echo "      ❌ 未通过"; _lint_rc=1; fi
  if [ "$SKIP_TL" -eq 1 ]; then
    echo "      · test-lint 已跳过（--skip-test-lint）"
  else
    echo "      [${_who}] test-lint …"
    if run_tl > "$TGT_LOG/testlint.$_who" 2>&1; then echo "      ✅ 通过"; else echo "      ❌ 未通过"; _tl_rc=1; fi
  fi
  if _bmsg=$(run_budget); then echo "      ✅ 预算：${_bmsg}"; else echo "      ⚠️  预算：${_bmsg}（不阻断升级，见 lint 段 1）"; fi
}

TGT_LOG=$(mktemp -d 2>/dev/null) || TGT_LOG="$TARGET/.keel-backup/tmp-logs"
mkdir -p "$TGT_LOG"

if [ "$DRY" -eq 0 ]; then
  echo "── 1. 升级前门禁"
  _lint_rc=0; _tl_rc=0
  gate_report before
  if [ "$_lint_rc" -ne 0 ] || [ "$_tl_rc" -ne 0 ]; then
    if [ "$FORCE" -eq 0 ]; then
      echo
      echo "❌ 升级前门禁已不通过。此时无法区分「本来就有问题」与「升级引入的问题」，"
      echo "   默认中止（文件未改动）。先修好，或确认与此无关后加 --force。"
      echo "   详情: $TGT_LOG"
      exit 1
    fi
    echo "   ⚠️  --force：带着升级前已失败的门禁继续（不做自动回滚判定）"
    PRE_BAD=1
  else
    PRE_BAD=0
  fi
fi

# ---------- 计划 / 应用 ----------
BK_DIR=""
if [ "$DRY" -eq 0 ]; then
  mkdir -p "$TARGET/.keel-backup"
  BK_DIR="$TARGET/.keel-backup/$(printf '%s' "$CUR" | tr '/ ' '__')-to-$(printf '%s' "$TOV" | tr '/ ' '__')-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$BK_DIR"
  cp -R "$TARGET/keel" "$BK_DIR/keel" || die 2 "备份失败: $BK_DIR"
  mkdir -p "$BK_DIR/local-mod"
  echo "── 2. 备份：${BK_DIR}（可用 --rollback 回滚）"
fi

echo "── 3. 按 manifest 分类处理"
UPDATED=0; ADDED=0; KEPT=0; MODIFIED=""
while IFS=$'\t' read -r cat rel mode hash; do
  case "$cat" in ''|\#*) continue ;; esac
  case "$cat" in
    kernel)
      srcf="$SRC_KEEL/$rel"; dstf="$TARGET/keel/$rel"
      [ -f "$srcf" ] || die 2 "模板宣称有 ${rel}，但文件不存在（manifest 与模板不一致）"
      if [ -n "$hash" ]; then
        ah=$(sha256_of "$srcf")
        [ "$ah" = "$hash" ] || die 2 "模板文件校验和不符: ${rel}（模板被改动或 manifest 过期 → 发布方跑 --regen-manifest）"
      fi
      # 本地修改检测：只对旧版有 manifest 的仓库成立
      if [ -f "$dstf" ] && [ -n "$OLD_MANIFEST" ]; then
        oh=$(awk -F'\t' -v p="$rel" '$1=="kernel" && $2==p {print $4}' "$OLD_MANIFEST")
        if [ -n "$oh" ] && [ "$(sha256_of "$dstf")" != "$oh" ]; then
          MODIFIED="$MODIFIED $rel"
          [ "$DRY" -eq 0 ] && { mkdir -p "$BK_DIR/local-mod/$(dirname "$rel")"; cp "$dstf" "$BK_DIR/local-mod/$rel"; }
        fi
      fi
      if [ "$DRY" -eq 1 ]; then
        echo "   ↑ 覆盖 $rel"
      else
        mkdir -p "$(dirname "$dstf")"; cp "$srcf" "$dstf"
        [ -n "$mode" ] && chmod "$mode" "$dstf" 2>/dev/null
      fi
      UPDATED=$((UPDATED + 1))
      ;;
    merge)
      idx="$TARGET/keel/$rel"
      if [ -f "$idx" ]; then
        if grep -qE '^keel-version:' "$idx"; then
          if [ "$DRY" -eq 1 ]; then
            echo "   ~ 改 $rel 的 keel-version 行 → ${TOV}（其余保留）"
          else
            sed -i.bak "s|^keel-version:.*|keel-version: $TOV|" "$idx" && rm -f "$idx.bak"
          fi
        else
          echo "   ⚠️  $rel 无 keel-version 行，未改（lint 段 2 会判死）"
        fi
        # 检索协议正文若与模板不一致 → 只告警，不覆盖（§12.3：不允许一键覆盖）
        _p1=$(awk '/^## 检索协议/{f=1;next} f&&/^## /{exit} f&&NF' "$SRC_KEEL/$rel" | sed 's/[[:space:]]//g')
        _p2=$(awk '/^## 检索协议/{f=1;next} f&&/^## /{exit} f&&NF' "$idx" | sed 's/[[:space:]]//g')
        [ "$_p1" = "$_p2" ] || echo "   ⚠️  $rel 的检索协议正文与 v$TOV 模板不同——未覆盖，请人工比对（§12.3）"
      fi
      ;;
    preserve)
      echo "   · 保留 ${rel}（采用方自定义）"
      KEPT=$((KEPT + 1))
      ;;
    additive)
      srcf="$SRC_KEEL/$rel"; dstf="$TARGET/keel/$rel"
      if [ -e "$dstf" ]; then
        KEPT=$((KEPT + 1))
      elif [ -d "$(dirname "$dstf")" ]; then
        if [ "$DRY" -eq 1 ]; then echo "   + 补上 ${rel}（新增文件）"; else
          mkdir -p "$(dirname "$dstf")"; cp "$srcf" "$dstf"
        fi
        ADDED=$((ADDED + 1))
      else
        echo "   · 跳过 ${rel}（父目录不存在，可能是你用 keel-lite 裁剪掉的层）"
      fi
      ;;
    *)
      echo "   ⚠️  未知分类 '$cat'（${rel}），跳过"
      ;;
  esac
done < "$SRC_KEEL/checks/manifest.tsv"

if [ "$DRY" -eq 1 ]; then
  echo "── dry-run：未改动任何文件，也未跑门禁"
  echo "   共 $UPDATED 个内核文件将覆盖、$ADDED 个新增文件将补齐、$KEPT 个自定义/已存在文件保留"
  exit 0
fi

# manifest 本身最后落盘（它是安装状态记录，不参与自哈希）
cp "$SRC_KEEL/checks/manifest.tsv" "$TARGET/keel/checks/manifest.tsv"

echo "── 4. 升级后门禁"
_lint_rc=0; _tl_rc=0
gate_report after

# ---------- 回滚判定 ----------
if [ "${PRE_BAD:-0}" -eq 0 ] && { [ "$_lint_rc" -ne 0 ] || [ "$_tl_rc" -ne 0 ]; }; then
  if [ "$NO_ROLLBACK" -eq 1 ]; then
    echo "❌ 升级后门禁失败且指定了 --no-rollback：文件保持升级后状态（备份在 ${BK_DIR}）"
    exit 4
  fi
  echo "❌ 升级后门禁失败 → 自动回滚到 v$CUR"
  rm -rf "$TARGET/keel" && cp -R "$BK_DIR/keel" "$TARGET/keel" \
    || die 2 "自动回滚失败！备份仍在: $BK_DIR/keel（手工执行 --rollback）"
  echo "   已回滚。详情: $TGT_LOG"
  exit 3
fi

# 备份保留最近 N 份（防止无限增长）
_n=0
for _d in $(ls -1dt "$TARGET"/.keel-backup/*/ 2>/dev/null); do
  _n=$((_n + 1))
  [ "$_n" -gt "$BACKUP_KEEP" ] && rm -rf "$_d"
done

# restore.sh：一条命令回到升级前（不依赖 VCS）
cat > "$BK_DIR/restore.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
rm -rf "$TARGET/keel"
cp -R "$BK_DIR/keel" "$TARGET/keel"
echo "已回滚到 v${CUR}（备份: ${BK_DIR}）"
EOF
chmod +x "$BK_DIR/restore.sh"

echo "──"
echo "✅ 升级完成：$CUR → ${TOV}（内核覆盖 $UPDATED · 新增 $ADDED · 保留 ${KEPT}）"
if [ -n "$MODIFIED" ]; then
  echo "⚠️  以下内核文件本地有改动，已被升级覆盖；原文件在 $BK_DIR/local-mod/："
  for _m in $MODIFIED; do echo "      - $_m"; done
fi
echo "   回滚：bash keel/checks/keel-upgrade.sh --rollback   （或 $BK_DIR/restore.sh）"
exit 0
