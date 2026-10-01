---
scope: now
status: active
last-verified: 2026-10-01
updated: 2026-10-01
keywords: [焦点, 交接]
---

# NOW · main

## 当前焦点
v3.1.0：按 ROI 全量推进评估改进项（P0 ×2 / P1 ×2 / P2 ×2 / P3 ×1），并收口发布。

## 本轮完成

- [x] P0 孤儿判定改"真实链接图"（lint §9 重写 + DESIGN §9.3 逐字同步 + 用例 37，ADR 0004）
- [x] P0 闭环钩子"验谎"：lint 第 16 项 + `verify-hooks.sh` + CI 复核 + 安装脚本自证（ADR 0005）
- [x] P1 单轮加载预算：`budget.env` 增 `BYTES_SESSION` + `load-estimate.sh` + 协议第 4 条落到命令（ADR 0006）
- [x] P1 `keel-lite.sh` 精简器（默认 dry-run，连带剥离 INDEX 路由行，裁剪后 lint 自证）
- [x] P2 MCP 只读服务 `checks/mcp/keel-mcp-server.py`（8 项自测）+ DESIGN §4.4（ADR 0007）
- [x] P2 检索增强接入位：DESIGN §9.5 + `check-mcp-config.sh`（恒 exit 0，只防"声明落空"）
- [x] P3 `scripts/release.sh`：把"先发布仓、后项目仓"从约定变成脚本（默认 dry-run）
- [x] 自测 36 例 → 38 例；修掉 install/verify hooks 传相对路径时的前缀匹配 bug
- [x] 本轮新坑已登记：`pitfalls/meta/link-syntax-example-becomes-real-link.md`

## 未完成 / 半途
- [ ] 两仓尚未 push：跑 `bash scripts/release.sh --apply`（顺序由脚本强制）
- [ ] 发布仓 CI 已含 MCP 自测；项目仓 CI 未加（当前由发布仓 CI 覆盖）

## 下一步（按优先级）
1. 跑 `bash scripts/release.sh`（先看 dry-run）→ 确认后 `--apply` 两仓发布
2. 视需要在项目仓 CI 补 MCP 自测与 `check-mcp-config.sh`
3. 评估下一轮：把 §8 协议第 4 条的 `load-estimate.sh` 接入会话开始流程（当前靠主动跑）

## 阻塞
| 卡在 | 解锁条件 | 绕行 |
|---|---|---|
| 无 | —— | —— |

## 本轮新发现的坑
- `pitfalls/meta/link-syntax-example-becomes-real-link.md`（triggers 初值 0）
