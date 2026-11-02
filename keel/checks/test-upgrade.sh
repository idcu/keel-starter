#!/usr/bin/env bash
# test-upgrade.sh —— keel-upgrade 自测入口（DESIGN.md §12.3 / ADR 0020）
# 用法: bash keel/checks/test-upgrade.sh [-v] [--keep]
# 退出码: 0 = 全部通过；1 = 有用例失败；2 = 环境缺 python3（跳过，不算失败）
#
# 为什么单列一个入口（不并进 test-lint.sh）：
#   test-lint 守的是"判据能不能判死"，本套件守的是"升级工具改文件改得对不对"。
#   两者的失败含义完全不同——混一个分母里，会让人看到"自测 50/51"却不知道
#   坏的是规则还是升级引擎。
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)

if ! command -v python3 >/dev/null 2>&1; then
  echo "⚠️  未找到 python3，跳过 keel-upgrade 自测（升级引擎本体不受影响）"
  exit 2
fi

exec python3 "$HERE/test-upgrade.py" "$@"
