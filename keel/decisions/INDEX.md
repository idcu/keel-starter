---
scope: meta
status: active
last-verified: 2026-09-30
keywords: [决策, ADR, 索引]
---

| # | 决策（一句话） | 状态 | → 文件 |
|---|---|---|---|
| 0001 | 预算：行数单约束 → 行数 × 字节 × 单行三约束，budget.env 为唯一真源 | active | [0001-budget-three-constraints.md](0001-budget-three-constraints.md) |
| 0002 | 入口规格机器验：keel-version / project-state 必填，点火锚点按原文检查 | active | [0002-machine-verified-entry.md](0002-machine-verified-entry.md) |
| 0003 | triggers 计数由 commit-msg 钩子自动完成，废除 AI 手工 +1 | active | [0003-hook-counted-triggers.md](0003-hook-counted-triggers.md) |
