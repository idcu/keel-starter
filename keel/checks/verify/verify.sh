#!/usr/bin/env bash
# verify.sh —— 完整验证清单入口（DESIGN.md §12.3 / ADR 0005）
# 用法: bash keel/checks/verify/verify.sh [--out verify-report.json] [--label 名称] [--strict]
# 退出码: 0 = 无 FAIL（允许 SKIP）；1 = 有 FAIL（--strict 时 SKIP 也算）；2 = 缺 python3
#
# 采用方复现：
#   bash keel/checks/verify/verify.sh --out verify-report.json
#   然后 check-verify-report.py --report verify-report.json --summary 生成发行说明一节。
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)

if ! command -v python3 >/dev/null 2>&1; then
  echo "⚠️  未找到 python3，跳过完整验证清单（各套件仍可单独运行）"
  exit 2
fi

exec python3 "$HERE/verify.py" "$@"
