---
scope: meta
status: active
last-verified: 2026-10-03
keywords: [决策, ADR, 索引, 性能, 批量化]
---

| # | 决策（一句话） | 状态 | → 文件 |
|---|---|---|---|
| 0001 | 预算：行数单约束 → 行数 × 字节 × 单行三约束，budget.env 为唯一真源 | active | [0001-budget-three-constraints.md](0001-budget-three-constraints.md) |
| 0002 | 入口规格机器验：keel-version / project-state 必填，点火锚点按原文检查 | active | [0002-machine-verified-entry.md](0002-machine-verified-entry.md) |
| 0003 | triggers 计数由 commit-msg 钩子自动完成，废除 AI 手工 +1 | active | [0003-hook-counted-triggers.md](0003-hook-counted-triggers.md) |
| 0004 | 孤儿判定改"真实链接图"，不再按文件名字符串匹配 | active | [0004-orphan-link-graph.md](0004-orphan-link-graph.md) |
| 0005 | 闭环钩子"验谎"：lint 第 16 项 + verify-hooks.sh | active | [0005-verify-hooks.md](0005-verify-hooks.md) |
| 0006 | 单轮加载量进预算真源（BYTES_SESSION）+ load-estimate.sh | active | [0006-session-load-budget.md](0006-session-load-budget.md) |
| 0007 | 兑现 MCP 只读落点，并把语义检索做成接入位 | active | [0007-mcp-readonly-and-retrieval-slot.md](0007-mcp-readonly-and-retrieval-slot.md) |
| 0008 | 把 lint 的 per-file fork 批量化（319s→97s），并给 lint 自身设时限预算 | active | [0008-batch-fork-and-time-budget.md](0008-batch-fork-and-time-budget.md) |
| 0009 | 遵守率只测客观事实，不采信 AI 自报（全赛道无人实现此指标） | active | [0009-compliance-rate-objective-only.md](0009-compliance-rate-objective-only.md) |
| 0010 | 版本声明与版本可获取必须同时成立（tag 缺失让 --ref 失效） | active | [0010-version-declared-and-fetchable.md](0010-version-declared-and-fetchable.md) |

