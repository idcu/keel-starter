#!/usr/bin/env bash
# keel-install.sh —— 把 Keel 装进你的项目（一条命令）
# 用法:
#   bash <(curl -fsSL https://gitee.com/idcu/keel-starter/raw/main/install.sh) <项目根>
#   bash install.sh <项目根>              # 已 clone 下来时
#   bash install.sh <项目根> --ref v3.2.0  # 指定版本
#
# 退出码: 0 = 装好且 lint 通过；1 = lint 未通过；2 = 用法/环境错误
#
# 为什么不用 npm（v3.2 实测结论）：
#   `npm pack` 会把 hooks/ 从 100755 打成 644 —— 而 lint 第 13 项要求
#   "闭环钩子本体存在**且可执行**"，所以从 npm 装出来的 keel 开箱即 fail。
#   git 则天然记录权限位（git ls-files -s 显示 100755），clone 下来就是对的。
#   本项目零编译、零运行时，引入 node 依赖树换可发现性不划算。
set -uo pipefail

REPO="https://gitee.com/idcu/keel-starter.git"
REF="main"
TARGET=""

for a in "$@"; do
  case "$a" in
    --ref) shift ;;
    --ref=*) REF="${a#--ref=}" ;;
    -*) echo "❌ 未知参数: $a"; exit 2 ;;
    *) TARGET="$a" ;;
  esac
done
# --ref 的值可能是下一个位置参数
while [ $# -gt 0 ]; do
  case "$1" in
    --ref) REF="${2:-main}"; shift 2 ;;
    *) shift ;;
  esac
done

[ -n "$TARGET" ] || { echo "用法: bash install.sh <项目根> [--ref v3.2.0]"; exit 2; }
command -v git >/dev/null 2>&1 || { echo "❌ 需要 git（本项目用 git 分发以保留钩子可执行位）"; exit 2; }
[ -d "$TARGET" ] || { echo "❌ 目录不存在: $TARGET"; exit 2; }
TARGET=$(cd "$TARGET" && pwd)

# 已有 keel/ 就地升级（不覆盖用户内容），否则全新复制
EXISTING=0
[ -d "$TARGET/keel" ] && EXISTING=1

tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
echo "keel-install · 目标=$TARGET · ref=$REF · 模式=$([ "$EXISTING" -eq 1 ] && echo '就地升级（保留你的内容）' || echo '全新安装')"

echo "── 1. 取模板"
if ! git clone --depth 1 --branch "$REF" "$REPO" "$tmp/starter" 2>/dev/null; then
  # 分支不存在时回落到默认分支 + 提示
  if ! git clone --depth 1 "$REPO" "$tmp/starter" 2>/dev/null; then
    echo "❌ 拉取失败: $REPO"
    echo "   也可手工下载后运行: bash install.sh <项目根>"
    exit 2
  fi
  echo "   ⚠️  ref '$REF' 不存在，已用默认分支（可用 --ref 指定 tag）"
fi
[ -d "$tmp/starter/keel" ] || { echo "❌ 仓库里没有 keel/ 目录，不是 keel-starter"; exit 2; }

echo "── 2. 装文件"
if [ "$EXISTING" -eq 1 ]; then
  # 只补缺失与工具链，**不覆盖**用户的 INDEX/NOW/pitfalls/decisions
  # （对应设计稿 §12.3：升级按字段增量合并，不允许一键覆盖）
  for f in checks/budget.env checks/keel-lint.sh checks/load-estimate.sh \
           checks/keel-lite.sh checks/verify-hooks.sh checks/install-hooks.sh \
           checks/check-mcp-config.sh checks/mcp/keel-mcp-server.py \
           checks/hooks/pre-commit checks/hooks/commit-msg; do
    if [ -e "$tmp/starter/keel/$f" ]; then
      if [ -e "$TARGET/keel/$f" ]; then
        echo "   · 保留 $f（你的版本）"
      else
        cp -R "$tmp/starter/keel/$f" "$TARGET/keel/$f" && echo "   + 补上 $f"
      fi
    fi
  done
  # 新增层（目录不存在才复制）
  for d in contracts env skills decisions; do
    [ -d "$TARGET/keel/$d" ] || { cp -R "$tmp/starter/keel/$d" "$TARGET/keel/$d" 2>/dev/null && echo "   + 补上 $d/"; }
  done
else
  cp -R "$tmp/starter/keel" "$TARGET/keel" && echo "   + 已复制 keel/（含 checks / hooks / 模板）"
fi

echo "── 3. 钩子可执行位（git 保留 100755，这里再确认一次）"
for h in pre-commit commit-msg; do
  f="$TARGET/keel/checks/hooks/$h"
  [ -f "$f" ] && { chmod +x "$f" 2>/dev/null; echo "   ✓ $h"; }
done

echo "── 4. 装钩子（core.hooksPath）"
bash "$TARGET/keel/checks/install-hooks.sh" "$TARGET" 2>&1 | sed 's/^/   /'

echo "── 5. 内核校验：必须 0 fail"
# 不把输出丢进 /dev/null：**新装的项目必然报"点火锚点缺失"**（这是设计意图，
# 不是故障）。若只说"lint 未通过"而不说判了什么，新用户会以为装坏了。
# **必须 cd 到目标目录再跑 lint**：install.sh 通常从别处调用（下载到 /tmp 再执行），
# 而 keel-lint.sh 的入参 `keel` 是**相对当前目录**解析的。
# 实测踩过：不 cd 时，cwd 在发布仓 → lint 校验的是发布仓自己（绿），
# 于是"装到新项目"这一步的验证全是假的——比不验证更坏。
lintout=$(cd "$TARGET" && bash keel/checks/keel-lint.sh keel 2>&1)
lint_rc=$?
if [ "$lint_rc" -eq 0 ]; then
  echo "   ✅ lint 通过"
else
  echo "   ❌ lint 未通过。以下是它判死的原因："
  printf '%s\n' "$lintout" | grep -E '^❌' | head -10 | sed 's/^/      /'
  # 注意：必须匹配 **lint 自己的报错文案**，不能匹配本脚本后面打印的提示语——
  # 否则会出现"提示说缺锚点、实际缺的是别的"这种自证陷阱（实测踩过：
  # 实际判死是「坑条目未登记」+「孤儿」，提示却说缺锚点）。
  # 判据：lint 报锚点缺失时原文含「锚点缺失或与 §4.1 原文不一致」。
  if printf '%s\n' "$lintout" | grep -q '锚点缺失或与'; then
    echo
    echo "   👉 缺的是**点火锚点**——那是第 1 步"贴锚点"还没做。"
    echo "      Keel 的检索协议写在 INDEX.md 里，但 AI 不会凭空去读它："
    echo "      协议在门内，钥匙必须在门外。这一句必须放进你的工具规则："
    echo
    echo "        任何任务开始前，先读 keel/INDEX.md 与其中指向的 NOW.md，并遵守 INDEX.md 里的检索协议。"
    echo
    echo "      放进 AGENTS.md / CLAUDE.md / .cursor/rules/keel.mdc 任一处即可。"
  else
    echo
    echo "   逐条跑一次看完整原因：bash keel/checks/keel-lint.sh keel"
  fi
  exit 1
fi

cat <<'EOF'

✅ 装好了。还差三步（缺任一步，这套系统等于不存在）：

  1. 点火——把这一句放进你的工具规则（CLAUDE.md / .cursor/rules/keel.mdc / 系统提示）：
       任何任务开始前，先读 keel/INDEX.md 与其中指向的 NOW.md，并遵守 INDEX.md 里的检索协议。
     协议写在 INDEX.md 里，但 AI 不会凭空去读——协议在门内，钥匙必须在门外。

  2. 填自己的内容——CONSTITUTION.md 里的「<项目名>」「<技术栈>」还是占位：
       编辑 keel/CONSTITUTION.md 写清身份、硬约束、人审关卡
       编辑 keel/INDEX.md 把路由表里的占位换成你项目的真实入口

  3. 小项目先裁剪——全量骨架带 6 个按需层，用不上就先裁掉：
       bash keel/checks/keel-lite.sh keel            # dry-run，看要删什么
       bash keel/checks/keel-lite.sh keel --apply    # 确认后执行

日常三个命令：
  bash keel/checks/keel-lint.sh keel    # 一致性校验：0 fail 才放行
  bash keel/checks/test-lint.sh         # lint 自测：38 例
  bash keel/checks/load-estimate.sh 关键词  # 本轮要读多少字节？超预算即非零退出
EOF
exit 0
