#!/usr/bin/env bash
# test-upgrade-matrix.sh —— 跨版本升级矩阵入口（DESIGN.md §12.3 / ADR 0020）
# 用法: bash keel/checks/test-upgrade-matrix.sh [-v]
#       KEEL_MATRIX_VERSIONS="3.6.1,3.7.4,3.8.0,3.9.0,current"  # 可配置格
#       KEEL_MATRIX_OFFLINE=1                             # 禁止联网取历史 tag
#       KEEL_MATRIX_NO_INSTALL_CELL=1                     # 跳过 ≤3.5.0 的 install 引导格
# 退出码: 0 = 无失败（可能含 SKIP，SKIP 在汇总单列「未验证」）；1 = 有格失败；2 = 缺 python3
#
# 为什么单列一个入口：矩阵跑的是「旧引擎 + 新模板」的真实组合，
# 和 test-upgrade（新引擎自测）的失败含义不同；混一个分母会让人误判。
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)

if ! command -v python3 >/dev/null 2>&1; then
  echo "⚠️  未找到 python3，跳过跨版本升级矩阵（升级引擎本体不受影响）"
  exit 2
fi

exec python3 "$HERE/test-upgrade-matrix.py" "$@"
