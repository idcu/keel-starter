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
  mv "$tmpm" "$M"  # keel-write:ok 发布方重算清单（源为 mktemp 临时文件）
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
    rm -rf "$TARGET/keel" \
      && cp -pR "$B/keel" "$TARGET/keel" || die 2 "回滚复制失败（原目录可能被占用）"  # keel-write:ok 整目录回滚
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

# ---------- 终态校验（v3.9.0 / §9.1-19）----------
# 为什么要有它：升级的**声明**（"✅ 升级完成"）与**事实**（磁盘上到底是什么样）
# 之间必须有一次独立复核。此前只要各分支没 die 就走到打印成功，而"没 die"只说明
# 每一步自己没报错，不说明拼起来是一个完整、可回滚、可续跑的升级结果。
final_verify() {
  _fv_bad=""
  _fv_from=$(pending_get "$PENDING" from)
  _fv_v=$(read_version "$TARGET/keel/INDEX.md")
  [ "$_fv_v" = "$TOV" ] || _fv_bad="${_fv_bad}
   - 版本不符：INDEX.md 是 ${_fv_v:-<空>}，期望 ${TOV}"
  # pending 此时必须已进入 done：真正的「清除」在调用方紧随其后做并复核。
  # 不在这里要求"文件不存在"——那样一旦校验失败，就没有 --resume 这条路了。
  [ "$(pending_stage "$PENDING")" = "done" ] || _fv_bad="${_fv_bad}
   - 断点状态未进入终态（stage=$(pending_stage "$PENDING")）"
  # "备份可回滚"看的是**备份树本身**，不是 restore.sh 是否存在：
  # 3.8.x 及更早的引擎不会预先写 restore.sh（v3.9.0 才提前生成），
  # 早先按"必须有 restore.sh"判，会让所有从旧版升上来的用户被误判失败（实测踩到）。
  if [ -z "${BK_DIR:-}" ] || [ ! -d "$BK_DIR/keel" ]; then
    _fv_bad="${_fv_bad}
   - 备份不可回滚：${BK_DIR:-<空>}"
  else
    _fv_bv=$(read_version "$BK_DIR/keel/INDEX.md")
    [ "$_fv_bv" = "${_fv_from:-$CUR}" ] || _fv_bad="${_fv_bad}
   - 备份版本不符：${_fv_bv:-<空>} ≠ ${_fv_from:-$CUR}"
  fi
  if ! bash "$TARGET/keel/checks/keel-upgrade.sh" --check-manifest "$TARGET/keel" >/dev/null 2>&1; then
    _fv_bad="${_fv_bad}
   - manifest 校验和与磁盘不一致（跑 --check-manifest 看细节）"
  fi
  _fv_tmp=$(find "$TARGET/keel" -name '*.keel-new.*' -type f 2>/dev/null | head -1)
  [ -z "$_fv_tmp" ] || _fv_bad="${_fv_bad}
   - 残留临时文件：${_fv_tmp#"$TARGET"/}"
  [ -z "$_fv_bad" ] || die 2 "终态校验失败，未声明成功（备份在 ${BK_DIR:-<空>}，可 --rollback）${_fv_bad}"
  echo "   终态校验：版本 / 断点终态 / 备份可回滚 / manifest / 临时文件 5 项均通过"
}

# ---------- 未完成升级：检测与续跑前校验 ----------
FROM_V="$CUR"
RESUME_STAGE=""
DONE_FILES=""; DONE_N=0
if [ -f "$PENDING" ]; then
  PTO=$(pending_get "$PENDING" to)
  PST=$(pending_stage "$PENDING")
  _pv=$(pending_get "$PENDING" from)
  [ -n "$_pv" ] && FROM_V="$_pv"
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
    # 上次已走完门禁、只是 pending 没删干净：仍要过终态校验才允许声明成功
    BK_DIR=$(pending_get "$PENDING" backup)
    final_verify
    rm -f "$PENDING"
    [ ! -f "$PENDING" ] || die 2 "断点状态未能清除: ${PENDING}"
    echo "✅ 上次升级已完成（残留的 pending 已清理，终态复核通过）"
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

# ---------- 单一写路径（v3.9.0 / §9.1-19）----------
# 为什么要有它：v3.8.0 修的是"每一处漏判"，但漏判的成因是**写动作分散**——
# kernel / additive / merge / manifest / pending / restore.sh 各自一套 cp、sed、
# printf 重定向，退出码逐个判断，漏一个就回到"静默成功"。这里收敛成一个函数：
# 内容从 stdin 读入 → 写临时文件 → 持久化 → 读回校验 → rename → 权限。
# 任一步失败即 die 2，且**目标文件保持原样**（临时文件清掉、不 rename）。
# 之后 record_file 用 AW_HASH 复核落盘内容，等于"写完再读回哈希"。
#
# $1=目标绝对路径 $2=权限(可空) $3=报错标签 $4=期望 sha256(可空)
# >>> keel-write-core（lint §9.1-19 豁免区间：唯一允许直接写文件的地方）
atomic_write() {
  _aw_dst="$1"; _aw_mode="${2:-}"; _aw_what="${3:-$1}"; _aw_want="${4:-}"
  _aw_dir=$(dirname "$_aw_dst")
  mkdir -p "$_aw_dir" 2>/dev/null \
    || die 2 "创建目录失败: ${_aw_what}（磁盘满或只读？）"
  _aw_tmp="${_aw_dst}.keel-new.$$"
  if ! cat > "$_aw_tmp" 2>/dev/null; then
    rm -f "$_aw_tmp"
    die 2 "写入失败: ${_aw_what}（磁盘满或只读？已完成 ${DONE_N} 个文件；修复后 --resume 或 --rollback）"
  fi
  # 持久化：GNU sync 支持按文件；BSD sync 不接受参数（会直接报错），此时跳过。
  # rename 的**可见性**不受影响，这里只是把"已经在页缓存里"落到介质。
  if sync --version >/dev/null 2>&1; then sync "$_aw_tmp" 2>/dev/null || true; fi
  AW_HASH=$(sha256_of "$_aw_tmp")
  if [ "$AW_HASH" = "__NO_SHA256__" ] || [ ! -s "$_aw_tmp" ]; then
    rm -f "$_aw_tmp"
    die 2 "写入后校验失败（空文件或算不出哈希）: ${_aw_what}；修复后 --resume 或 --rollback"
  fi
  if [ -n "$_aw_want" ] && [ "$AW_HASH" != "$_aw_want" ]; then
    rm -f "$_aw_tmp"
    die 2 "写入后校验失败（哈希不符）: ${_aw_what}（期望 ${_aw_want}，实际 ${AW_HASH}）"
  fi
  if ! mv -f "$_aw_tmp" "$_aw_dst" 2>/dev/null; then
    rm -f "$_aw_tmp"
    die 2 "写入失败: ${_aw_what}（rename 失败，磁盘满或只读？已完成 ${DONE_N} 个文件）"
  fi
  [ -n "$_aw_mode" ] && chmod "$_aw_mode" "$_aw_dst" 2>/dev/null
  return 0
}
# <<< keel-write-core

# ---------- 断点状态写入（唯一写路径）----------
pending_write() {   # $1 = 阶段名
  atomic_write "$PENDING" "" "断点状态" "" <<EOF
# keel-upgrade pending v1（断点恢复状态，勿手改）
from=${FROM_V:-$CUR}
to=$TOV
stage=$1
backup=${BK_DIR:-}
${DONE_FILES}
EOF
}
done_has() { printf '%s' "$DONE_FILES" | awk -F'\t' -v p="$1" '$1=="file" && $2==p {f=1} END{exit(f?0:1)}'; }
record_file() {     # $1=相对路径 $2=写入时算出的哈希（可空）：落盘后再读回复核
  _rf="$TARGET/keel/$1"
  _rh=$(sha256_of "$_rf"); _rm=$(file_mode "$_rf")
  # 写在同一台机器上却"写进去的哈希"与"读回来的哈希"不同，只可能是写入/替换
  # 没走同一条路径（或 fs 损坏）。此时若继续记录，--resume 会信任一个假的完成状态。
  if [ -n "${2:-}" ] && [ "$_rh" != "$2" ]; then
    die 2 "写入后校验失败（读回的哈希与写入内容不符）: $1（可 --rollback）"
  fi
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
    _bkbase="$TARGET/.keel-backup/$(printf '%s' "$CUR" | tr '/ ' '__')-to-$(printf '%s' "$TOV" | tr '/ ' '__')-$(date +%Y%m%d-%H%M%S)"
    # 同一秒内重试会撞名：上一次失败留下的**残备份**还在原路径上，`cp -pR src dst`
    # 遇到已存在的 dst 会复制成 dst/keel（嵌套一层），终态校验就读不到 $BK_DIR/keel/INDEX.md。
    # 所以目录名必须唯一（实测：备份失败后立刻 --resume，必然撞在同一秒）。
    BK_DIR="$_bkbase"; _bn=1
    while [ -e "$BK_DIR" ]; do BK_DIR="${_bkbase}-${_bn}"; _bn=$((_bn + 1)); done
    mkdir -p "$BK_DIR"
    cp -pR "$TARGET/keel" "$BK_DIR/keel" || die 2 "备份失败: $BK_DIR（磁盘满或只读？）"  # keel-write:ok 备份整目录
    mkdir -p "$BK_DIR/local-mod"
    # restore.sh 在**备份后立刻**生成：此刻空间最充裕，且之后任何阶段失败都已有回滚入口。
    # 它是辅助产物，写不进去只告警（--rollback 仍可用），所以放在子 shell 里接住 die。
    if ! (
      atomic_write "$BK_DIR/restore.sh" "755" "restore.sh" "" <<EOF
#!/usr/bin/env bash
set -euo pipefail
rm -rf "$TARGET/keel"
cp -pR "$BK_DIR/keel" "$TARGET/keel"
echo "已回滚到 v${CUR}（备份: ${BK_DIR}）"
EOF
    ); then
      echo "⚠️  未能写入 ${BK_DIR}/restore.sh（空间不足？）；回滚请用 --rollback"
    fi
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
  AW_HASH=""   # 每轮清空：绝不让上一个文件的哈希被下一个文件误用
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
          [ "$DRY" -eq 0 ] && { mkdir -p "$BK_DIR/local-mod/$(dirname "$rel")"; cp "$dstf" "$BK_DIR/local-mod/$rel"; }  # keel-write:ok 本地改动留档
        fi
      fi
      if [ "$DRY" -eq 1 ]; then
        echo "   ↑ 覆盖 $rel"
      else
        # v3.9.0：所有落盘走 atomic_write（temp+sync+读回校验+rename）。它保证
        # ① 执行中的旧 inode 不被截断（覆盖 keel-upgrade.sh 自身时也不自杀）；
        # ② ENOSPC/EACCES 时目标文件保持原样、临时文件清掉；
        # ③ 写入内容的哈希先与 manifest 核对，rename 后再由 record_file 复核。
        atomic_write "$dstf" "$mode" "$rel" "$hash" < "$srcf"
        record_file "$rel" "$AW_HASH"; pending_write applying
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
            # v3.9.0：sed 只产出内容，落盘仍走 atomic_write。写前记行数，写后核对
            # "版本行是 TOV 且行数没变"——防止 sed 中途失败却把半截内容 rename 过去。
            _mlc=$(awk 'END{print NR}' "$idx")
            # 先把 sed 结果落到临时文件，再让 atomic_write 从文件读——不要写
            # `sed | atomic_write`：管道里的函数跑在子 shell，AW_HASH 传不回来，
            # 会让 record_file 拿到上一次写动作的旧哈希（本轮自测就是这么炸的）。
            _mtmp=$(mktemp) || die 2 "无法创建临时文件（磁盘满？）"
            if ! sed "s|^keel-version:.*|keel-version: $TOV|" "$idx" > "$_mtmp"; then
              rm -f "$_mtmp"; die 2 "生成 ${rel} 新内容失败（已完成 ${DONE_N} 个文件）"
            fi
            atomic_write "$idx" "$(file_mode "$idx")" "$rel" "" < "$_mtmp"
            rm -f "$_mtmp"
            _nlc=$(awk 'END{print NR}' "$idx")
            if [ "$_nlc" != "$_mlc" ] || ! grep -qE "^keel-version:[[:space:]]*${TOV}[[:space:]]*$" "$idx"; then
              die 2 "写入后校验失败（行数或版本行不符）: ${rel}（可 --rollback）"
            fi
            record_file "$rel" "$AW_HASH"; pending_write applying
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
          _ah=$(sha256_of "$srcf")
          atomic_write "$dstf" "$mode" "$rel" "$_ah" < "$srcf"
          record_file "$rel" "$AW_HASH"; pending_write applying
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
atomic_write "$TARGET/keel/checks/manifest.tsv" \
  "$(file_mode "$SRC_KEEL/checks/manifest.tsv")" "checks/manifest.tsv" "" \
  < "$SRC_KEEL/checks/manifest.tsv"
record_file "checks/manifest.tsv" "$AW_HASH"
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
  rm -rf "$TARGET/keel" \
    && cp -pR "$BK_DIR/keel" "$TARGET/keel" || die 2 "自动回滚失败！备份仍在: $BK_DIR/keel（手工执行 --rollback）"  # keel-write:ok 整目录回滚
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

# restore.sh 在备份阶段就已生成（§2），此时空间可能已被 apply 吃掉，不再重写。
[ -f "$BK_DIR/restore.sh" ] || echo "⚠️  备份目录缺 restore.sh（回滚请用 --rollback）"

# 先落 stage=done 再复核，最后才清除 pending：任何一步失败都还留着续跑的路。
pending_write done
# 终态校验必须在**打印成功之前**：所有成功信息只能出现在这行之后。
final_verify
rm -f "$PENDING"
[ ! -f "$PENDING" ] || die 2 "断点状态未能清除: ${PENDING}"

echo "──"
echo "✅ 升级完成：$CUR → ${TOV}（内核覆盖 $UPDATED · 新增 $ADDED · 保留 ${KEPT}$([ "$SKIPPED" -gt 0 ] && echo " · 续跑跳过 ${SKIPPED}")）"
if [ -n "$MODIFIED" ]; then
  echo "⚠️  以下内核文件本地有改动，已被升级覆盖；原文件在 $BK_DIR/local-mod/："
  for _m in $MODIFIED; do echo "      - $_m"; done
fi
echo "   回滚：bash keel/checks/keel-upgrade.sh --rollback   （或 $BK_DIR/restore.sh，若有）"
exit 0
