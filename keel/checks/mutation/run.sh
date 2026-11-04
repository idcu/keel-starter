#!/usr/bin/env bash
# run.sh —— 变异测试试点的薄壳（DESIGN.md §9.1）
# 用法: bash keel/checks/mutation/run.sh [--out mutation.json] [--jobs N] [-v]
# 退出码: 0 = 全部变异体被杀；1 = 有存活；2 = 基线/环境错误
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
command -v python3 >/dev/null 2>&1 || { echo "缺 python3（变异测试是测试工具，不是分发依赖）"; exit 2; }
exec python3 "$HERE/mutation.py" "$@"
