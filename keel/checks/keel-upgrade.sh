#!/usr/bin/env bash
# keel-upgrade.sh —— 已接入仓库的 keel 增量升级（DESIGN.md §12.3 / ADR 0020）
#
# 用法:
#   bash keel/checks/keel-upgrade.sh [--target <项目根>] [--to vX.Y.Z]
#                                    [--from <模板目录>] [--dry-run] [--force]
#                                    [--no-rollback] [--skip-test-lint] [--resume]
#   bash keel/checks/keel-upgrade.sh --rollback [备份目录]
#   bash keel/checks/keel-upgrade.sh --resume   # 续跑上次被中断的升级（只处理剩余文件）
#   bash keel/checks/keel-upgrade.sh --regen-manifest <keel目录>   # 发布方专用
#   bash keel/checks/keel-upgrade.sh --check-manifest <keel目录>   # 发布方 / CI
#
# 退出码:
#   0 = 升级完成 / 已是目标版本（无需升级）/ 回滚完成 / manifest 一致
#   1 = 升级前门禁未通过（未改动任何文件）/ manifest 与实际文件不一致
#   2 = 用法 / 环境 / 模板校验错误
#   3 = 升级后门禁失败，已自动回滚
#   4 = 升级后门禁失败，未回滚（--no-rollback）
#   5 = 存在未完成的升级（需 --resume 或 --rollback）/ 续跑前一致性校验失败
#
# 断点恢复（v3.7.1）：apply 期间在 <项目根>/.keel-upgrade.pending 记录目标版本、
# 阶段（preflight/backup/applying/gate/done）、已完成文件与各自 sha256、备份目录、
# 原版本号；每次写入都是「临时文件 + rename」原子替换。中断后重新运行会提示两条路；
# --resume 先按记录校验已完成文件的 sha256，不符则拒绝续跑（只允许回滚），
# 目标版本与本次命令不一致时同样拒绝（防止跨版本续跑出混合态）。
#
# 故障注入（仅供 test-upgrade 使用）：必须同时设 KEEL_UPGRADE_TEST_HOOKS=1 与
# KEEL_UPGRADE_FAULT=after:backup|after:file:N|before:gate，才会在对应点 SIGKILL 自己。
# 默认关闭；只设 FAULT 不设 TEST_HOOKS 时会被忽略并告警，正常路径判据不受影响。
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
REGEN=""; CHECK=""; RB=""; RB_SET=0; RESUME=0

usage() {
  sed -n '3,27p' "$0" | sed 's/^# \{0,1\}//'
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
    --resume) RESUME=1; shift ;;
    --regen-manifest) [ $# -ge 2 ] || die 2 "--regen-manifest 后面要跟 keel 目录"; REGEN="$2"; shift 2 ;;
    --check-manifest) [ $# -ge 2 ] || die 2 "--check-manifest 后面要跟 keel 目录"; CHECK="$2"; shift 2 ;;
    --check-manifest=*) CHECK="${1#--check-manifest=}"; shift ;;
    --rollback) RB_SET=1; shift; [ $# -gt 0 ] && case "$1" in -*) ;; *) RB="$1"; shift ;; esac ;;
    -h|--help) usage; exit 0 ;;
    -*) die 2 "未知参数: $1" ;;
    *) [ -z "$TARGET" ] || die 2 "只能给一个项目根（多了: $1）"; TARGET="$1"; shift ;;
  esac
done

# 故障注入防护：只认「测试显式开启」的双开关，正常使用不受任何影响。
if [ -n "${KEEL_UPGRADE_FAULT:-}" ] && [ "${KEEL_UPGRADE_TEST_HOOKS:-0}" != "1" ]; then
  echo "⚠️  忽略 KEEL_UPGRADE_FAULT（故障注入仅在 KEEL_UPGRADE_TEST_HOOKS=1 时生效）"
fi

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

# ---------- 断点状态文件 ----------
pending_get() { sed -n "s/^$2=//p" "$1" 2>/dev/null | head -1; }
pending_stage() { pending_get "$1" stage; }

# 故障注入：必须 KEEL_UPGRADE_TEST_HOOKS=1 + KEEL_UPGRADE_FAULT=<点> 同时成立。
# 用 SIGKILL 而不是 exit：EXIT trap 不会跑，才像真的被 kill / 断电。
fault_point() {
  [ "${KEEL_UPGRADE_TEST_HOOKS:-0}" = "1" ] || return 0
  [ "${KEEL_UPGRADE_FAULT:-}" = "$1" ] || return 0
  echo "💥 故障注入: $1（模拟中断）"
  kill -KILL $$ 2>/dev/null
  exit 137
}

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
  P="$TARGET/.keel-upgrade.pending"
  B="$RB"
  # 有 pending 时优先用它记录的备份目录（中断后用户不必自己找目录名）
  if [ -z "$B" ] && [ -f "$P" ]; then B=$(pending_get "$P" backup); fi
  if [ -z "$B" ]; then
    B=$(ls -1dt "$TARGET"/.keel-backup/*/ 2>/dev/null | head -1 | sed 's#/$##')
  fi
  if [ -n "$B" ] && [ -d "$B/keel" ]; then
    rm -rf "$TARGET/keel" && cp -pR "$B/keel" "$TARGET/keel" \
      || die 2 "回滚复制失败（原目录可能被占用）"
    echo "✅ 已回滚到备份: $B"
  elif [ -f "$P" ] && [ "$(pending_stage "$P")" = "preflight" ]; then
    echo "ℹ️  中断发生在改动文件之前（preflight），无需还原"
  else
    die 2 "找不到可用的备份目录（$TARGET/.keel-backup）"
  fi
  if [ -f "$P" ]; then rm -f "$P" && echo "   已清除未完成升级状态"; fi
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
PENDING="$TARGET/.keel-upgrade.pending"

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
  # 续跑时若没给 --from，用 pending 记录的目标版本对应的 tag，避免 main 已前进导致跨版本续跑
  if [ -z "$TO" ] && [ "$RESUME" -eq 1 ] && [ -f "$PENDING" ]; then
    _pto=$(pending_get "$PENDING" to)
    [ -n "$_pto" ] && ref="v${_pto}"
  fi
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

# ---------- 未完成升级：检测与续跑前校验 ----------
RESUME_STAGE=""
DONE_FILES=""; DONE_N=0
if [ -f "$PENDING" ]; then
  PTO=$(pending_get "$PENDING" to)
  PST=$(pending_stage "$PENDING")
  if [ "$RESUME" -eq 0 ]; then
    echo "⚠️  检测到一次未完成的升级：$PENDING"
    echo "   状态：$CUR → ${PTO}（阶段 ${PST}）"
    echo "   续跑：bash keel/checks/keel-upgrade.sh --target $TARGET --resume"
    echo "   回滚：bash keel/checks/keel-upgrade.sh --target $TARGET --rollback"
    echo "   （续跑前会校验已完成文件的 sha256，不一致则只允许回滚）"
    exit 5
  fi
  # 目标版本不一致 → 拒绝续跑（跨版本续跑会得到新旧混杂的 keel/）
  if [ "$PTO" != "$TOV" ]; then
    echo "❌ 拒绝续跑：pending 的目标版本是 v${PTO}，本次命令的目标是 v${TOV}"
    echo "   只允许回滚：bash keel/checks/keel-upgrade.sh --target $TARGET --rollback"
    exit 5
  fi
  if [ "$PST" = "done" ]; then
    rm -f "$PENDING"
    echo "✅ 上次升级已完成（残留的 pending 已清理）"
    exit 0
  fi
  RESUME_STAGE="$PST"
  BK_DIR=$(pending_get "$PENDING" backup)
  _bad=""
  while IFS=$'\t' read -r _k _rel _h _m; do
    [ "$_k" = "file" ] || continue
    DONE_FILES="${DONE_FILES}file	${_rel}	${_h}	${_m}
"
    DONE_N=$((DONE_N + 1))
    _f="$TARGET/keel/$_rel"
    if [ ! -f "$_f" ]; then
      _bad="${_bad}
   - 缺失: $_rel"
    elif [ "$(sha256_of "$_f")" != "$_h" ]; then
      _bad="${_bad}
   - 已被外部改动: $_rel"
    fi
  done < "$PENDING"
  # 已完成文件被改动 → 续跑会把"外部改动"和"升级内容"搅在一起，只允许整目录回滚
  if [ -n "$_bad" ]; then
    echo "❌ 拒绝续跑：已完成文件与断点记录不一致$_bad"
    echo "   只允许回滚：bash keel/checks/keel-upgrade.sh --target $TARGET --rollback"
    exit 5
  fi
  if [ "$PST" != "preflight" ] && { [ -z "$BK_DIR" ] || [ ! -d "$BK_DIR/keel" ]; }; then
    echo "❌ 拒绝续跑：断点记录的备份目录不可用（${BK_DIR:-<空>}），无法保证可回滚"
    exit 5
  fi
  echo "↻ 续跑上次中断的升级：$CUR → ${PTO}（阶段 ${PST}，已完成 ${DONE_N} 个文件）"
elif [ "$RESUME" -eq 1 ]; then
  die 2 "--resume：没有未完成的升级（$PENDING 不存在）"
fi

# 续跑时：backup 及之后阶段的前置门禁与备份都已成立，不必重做
SKIP_PRE=0; SKIP_BK=0
if [ "$RESUME" -eq 1 ] && [ -f "$PENDING" ]; then
  case "$RESUME_STAGE" in
    ""|preflight) ;;
    *) SKIP_PRE=1; SKIP_BK=1 ;;
  esac
fi

if [ "$CUR" = "$TOV" ] && [ "$FORCE" -eq 0 ] && [ "$RESUME" -eq 0 ]; then
  echo "✅ 已是 v${TOV}，无需升级（--force 可强制重放一次）"
  exit 0
fi
if ver_gt "$CUR" "$TOV"; then
  die 2 "目标版本 $TOV 低于当前 ${CUR}——本工具不支持降级；回滚请用 --rollback"
fi

# ---------- 断点状态写入（临时文件 + rename，避免状态文件自身写坏）----------
pending_write() {   # $1 = 阶段名
  _pt="$PENDING.tmp.$$"
  # v3.8.0：写入失败必须显式失败。磁盘满时原实现会「写 temp 失败 → mv 失败」，
  # 而两次失败都被忽略，调用方以为状态已记下，实际 pending 停在上一版——
  # 那一刻断点语义已经错了，却没有任何输出。现在任一步失败都 die 2，
  # 且**上一版 pending 原样保留**（temp 清掉、不 rename），--resume 仍可用。
  if ! {
    printf '# keel-upgrade pending v1（断点恢复状态，勿手改）\n'
    printf 'from=%s\n' "$CUR"
    printf 'to=%s\n' "$TOV"
    printf 'stage=%s\n' "$1"
    printf 'backup=%s\n' "${BK_DIR:-}"
    [ -z "$DONE_FILES" ] || printf '%s' "$DONE_FILES"
  } > "$_pt"; then
    rm -f "$_pt"
    die 2 "断点状态写入失败（磁盘满或只读？）: ${PENDING}；上一版状态保留，腾出空间后 --resume"
  fi
  if ! mv -f "$_pt" "$PENDING"; then
    rm -f "$_pt"
    die 2 "断点状态替换失败（磁盘满或只读？）: ${PENDING}；上一版状态保留，腾出空间后 --resume"
  fi
}
done_has() { printf '%s' "$DONE_FILES" | awk -F'\t' -v p="$1" '$1=="file" && $2==p {f=1} END{exit(f?0:1)}'; }
record_file() {     # $1 = 相对路径：记录落盘后的真实字节哈希与权限
  _rf="$TARGET/keel/$1"
  _rh=$(sha256_of "$_rf"); _rm=$(file_mode "$_rf")
  DONE_FILES="${DONE_FILES}file	${1}	${_rh}	${_rm}
"
  DONE_N=$((DONE_N + 1))
}

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

if [ "$DRY" -eq 0 ] && [ "$SKIP_PRE" -eq 0 ]; then
  pending_write preflight
  echo "── 0. 断点状态：${PENDING}（中断后 --resume 续跑 / --rollback 回滚）"
  echo "── 1. 升级前门禁"
  _lint_rc=0; _tl_rc=0
  gate_report before
  if [ "$_lint_rc" -ne 0 ] || [ "$_tl_rc" -ne 0 ]; then
    if [ "$FORCE" -eq 0 ]; then
      echo
      echo "❌ 升级前门禁已不通过。此时无法区分「本来就有问题」与「升级引入的问题」，"
      echo "   默认中止（文件未改动）。先修好，或确认与此无关后加 --force。"
      echo "   详情: $TGT_LOG"
      rm -f "$PENDING"      # 未改动任何文件，断点状态无意义
      exit 1
    fi
    echo "   ⚠️  --force：带着升级前已失败的门禁继续（不做自动回滚判定）"
    PRE_BAD=1
  else
    PRE_BAD=0
  fi
elif [ "$DRY" -eq 0 ] && [ "$SKIP_PRE" -eq 1 ]; then
  echo "── 1. 升级前门禁：上次中断前已通过（续跑跳过）"
  PRE_BAD=0
fi

# ---------- 计划 / 应用 ----------
if [ "$DRY" -eq 0 ]; then
  if [ "$SKIP_BK" -eq 1 ]; then
    echo "── 2. 沿用断点备份：${BK_DIR}（续跑不重新备份）"
  else
    mkdir -p "$TARGET/.keel-backup"
    BK_DIR="$TARGET/.keel-backup/$(printf '%s' "$CUR" | tr '/ ' '__')-to-$(printf '%s' "$TOV" | tr '/ ' '__')-$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$BK_DIR"
    cp -pR "$TARGET/keel" "$BK_DIR/keel" || die 2 "备份失败: $BK_DIR（磁盘满或只读？）"
    mkdir -p "$BK_DIR/local-mod"
    pending_write backup
    echo "── 2. 备份：${BK_DIR}（可用 --rollback 回滚）"
    fault_point after:backup
  fi
fi

echo "── 3. 按 manifest 分类处理"
# temp+mv 的中间态可能被 SIGKILL 留在树里（不在清单、也不该被 lint 看见），先清掉
find "$TARGET/keel" -name '*.keel-new.*' -type f -exec rm -f {} + 2>/dev/null || true
UPDATED=0; ADDED=0; KEPT=0; SKIPPED=0; MODIFIED=""
while IFS=$'\t' read -r cat rel mode hash; do
  case "$cat" in ''|\#*) continue ;; esac
  case "$cat" in
    kernel)
      srcf="$SRC_KEEL/$rel"; dstf="$TARGET/keel/$rel"
      if done_has "$rel"; then echo "   ↷ 已完成，跳过 $rel"; SKIPPED=$((SKIPPED + 1)); continue; fi
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
        # v3.8.0：写入失败必须显式失败，且**先写临时文件再 rename**。
        # ① `cp` 的退出码原实现没人看，磁盘满会留下截断文件、并把残片哈希记进 pending；
        # ② 直接覆盖 `keel-upgrade.sh` 本身时，正在执行的 bash 可能读到被截断的脚本
        #    （实测 tmpfs 写满后该文件变成 0 字节，进程仍打印"升级完成"）。
        # temp + mv 后：执行中的旧 inode 不被截断，失败也只留下可清理的临时文件。
        mkdir -p "$(dirname "$dstf")" \
          || die 2 "创建目录失败: $(dirname "$rel")（磁盘满或只读？）"
        _tmpf="${dstf}.keel-new.$$"
        if ! cp "$srcf" "$_tmpf"; then
          rm -f "$_tmpf"
          die 2 "写入失败: ${rel}（磁盘满或只读？已完成 ${DONE_N} 个文件；修复后 --resume 或 --rollback）"
        fi
        if ! mv -f "$_tmpf" "$dstf"; then
          rm -f "$_tmpf"
          die 2 "写入失败: ${rel}（rename 失败，磁盘满或只读？已完成 ${DONE_N} 个文件）"
        fi
        [ -n "$mode" ] && chmod "$mode" "$dstf" 2>/dev/null
        record_file "$rel"; pending_write applying
        fault_point "after:file:${DONE_N}"
      fi
      UPDATED=$((UPDATED + 1))
      ;;
    merge)
      idx="$TARGET/keel/$rel"
      if [ -f "$idx" ]; then
        if done_has "$rel"; then echo "   ↷ 已完成，跳过 $rel"; SKIPPED=$((SKIPPED + 1)); continue; fi
        if grep -qE '^keel-version:' "$idx"; then
          if [ "$DRY" -eq 1 ]; then
            echo "   ~ 改 $rel 的 keel-version 行 → ${TOV}（其余保留）"
          else
            # v3.8.0：同 kernel 分支——sed 写失败（磁盘满）不得静默。
            if ! sed -i.bak "s|^keel-version:.*|keel-version: $TOV|" "$idx"; then
              rm -f "$idx.bak"
              die 2 "写入失败: ${rel}（磁盘满或只读？已完成 ${DONE_N} 个文件；修复后 --resume 或 --rollback）"
            fi
            rm -f "$idx.bak"
            record_file "$rel"; pending_write applying
            fault_point "after:file:${DONE_N}"
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
      if done_has "$rel"; then echo "   ↷ 已完成，跳过 ${rel}"; SKIPPED=$((SKIPPED + 1)); continue; fi
      if [ -e "$dstf" ]; then
        KEPT=$((KEPT + 1))
      elif [ -d "$(dirname "$dstf")" ]; then
        if [ "$DRY" -eq 1 ]; then echo "   + 补上 ${rel}（新增文件）"; else
          mkdir -p "$(dirname "$dstf")" \
            || die 2 "创建目录失败: $(dirname "$rel")（磁盘满或只读？）"
          _tmpf="${dstf}.keel-new.$$"
          if ! cp "$srcf" "$_tmpf"; then
            rm -f "$_tmpf"
            die 2 "写入失败: ${rel}（磁盘满或只读？已完成 ${DONE_N} 个文件；修复后 --resume 或 --rollback）"
          fi
          if ! mv -f "$_tmpf" "$dstf"; then
            rm -f "$_tmpf"
            die 2 "写入失败: ${rel}（rename 失败，磁盘满或只读？已完成 ${DONE_N} 个文件）"
          fi
          record_file "$rel"; pending_write applying
          fault_point "after:file:${DONE_N}"
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
if ! cp "$SRC_KEEL/checks/manifest.tsv" "$TARGET/keel/checks/manifest.tsv.keel-new.$$"; then
  rm -f "$TARGET/keel/checks/manifest.tsv.keel-new.$$"
  die 2 "写入 manifest 失败（磁盘满或只读？）；已完成 ${DONE_N} 个文件，修复后 --resume"
fi
mv -f "$TARGET/keel/checks/manifest.tsv.keel-new.$$" "$TARGET/keel/checks/manifest.tsv" \
  || die 2 "替换 manifest 失败（磁盘满或只读？）；已完成 ${DONE_N} 个文件，修复后 --resume"
record_file "checks/manifest.tsv"
pending_write gate

echo "── 4. 升级后门禁"
_lint_rc=0; _tl_rc=0
fault_point before:gate
gate_report after

# ---------- 回滚判定 ----------
if [ "${PRE_BAD:-0}" -eq 0 ] && { [ "$_lint_rc" -ne 0 ] || [ "$_tl_rc" -ne 0 ]; }; then
  if [ "$NO_ROLLBACK" -eq 1 ]; then
    echo "❌ 升级后门禁失败且指定了 --no-rollback：文件保持升级后状态（备份在 ${BK_DIR}）"
    echo "   断点状态保留：修好问题后可 --resume 只重跑门禁，或 --rollback 整目录还原"
    exit 4
  fi
  echo "❌ 升级后门禁失败 → 自动回滚到 v$CUR"
  rm -rf "$TARGET/keel" && cp -pR "$BK_DIR/keel" "$TARGET/keel" \
    || die 2 "自动回滚失败！备份仍在: $BK_DIR/keel（手工执行 --rollback）"
  rm -f "$PENDING"
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
cp -pR "$BK_DIR/keel" "$TARGET/keel"
echo "已回滚到 v${CUR}（备份: ${BK_DIR}）"
EOF
chmod +x "$BK_DIR/restore.sh"
[ -f "$BK_DIR/restore.sh" ] || echo "⚠️  未能写入 ${BK_DIR}/restore.sh（空间不足？）；回滚请用 --rollback"

echo "──"
echo "✅ 升级完成：$CUR → ${TOV}（内核覆盖 $UPDATED · 新增 $ADDED · 保留 ${KEPT}$([ "$SKIPPED" -gt 0 ] && echo " · 续跑跳过 ${SKIPPED}")）"
if [ -n "$MODIFIED" ]; then
  echo "⚠️  以下内核文件本地有改动，已被升级覆盖；原文件在 $BK_DIR/local-mod/："
  for _m in $MODIFIED; do echo "      - $_m"; done
fi
pending_write done
rm -f "$PENDING"
echo "   回滚：bash keel/checks/keel-upgrade.sh --rollback   （或 $BK_DIR/restore.sh）"
exit 0
