#!/usr/bin/env bash
# test-wiring.sh —— 入口级接线审计的薄壳（DESIGN.md §12.3）
# 用法: bash keel/checks/wiring/test-wiring.sh [--out wiring.json] [-v]
# 退出码: 0 = 全部入口有判死用例且通过；1 = 有用例失败；2 = 缺 python3
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
command -v python3 >/dev/null 2>&1 || { echo "缺 python3（接线审计是测试工具，不是分发依赖）"; exit 2; }
exec python3 "$HERE/test-wiring.py" "$@"
