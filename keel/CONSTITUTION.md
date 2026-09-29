---
scope: meta
status: active
last-verified: 2026-09-30
keywords: [宪法, 红线, 人审, 状态机]
---

# CONSTITUTION

> 这里不是"最佳实践建议"，是**违反就打回**。规格见《Keel 设计稿》§5.2。
> 只放硬约束与人审关卡；其余规则一律在 INDEX.md 及其路由之内。

## 身份

本项目是 <项目名>，技术栈 <...>，目标 <一句话>，owner <谁>。

<!-- 这是全库唯一允许"写愿望"的地方；其余文档只写现状。 -->

## 硬约束（违反即打回）

1. 禁止跨层调用：<模块A> 不得 import <模块B>
2. 禁止在客户端存储任何密钥 / token；`env/` 只记录来源，不记录值
3. 契约只能定义在 `contracts/`，其他位置不得重复定义
4. 单次会话 Keel 加载总量 ≤5k token（见 @INDEX.md；数字真源是 checks/budget.env）

<!-- 按项目实际情况增删。每条都得是"能被判死"的：写不出检查方式的，不是硬约束，是愿望。 -->

## 人审关卡（AI 不得自行决定）

| 改动类型 | 审批 | 留痕 | 时限 |
|---|---|---|---|
| 资金 / 支付 / 退款 | owner + 跨职能一人（双签） | decisions/ + PR | 24h |
| 权限 / 鉴权 / 数据删除 | owner | PR + decisions/（删除类必记） | 48h |
| contracts/ 契约变更 | owner + 契约 owner | decisions/ | 24h |
| 引入新第三方依赖 | owner | decisions/ | 48h |
| frozen 期任何契约改动 | 例外通道：双签 + 记例外 | decisions/ | 24h |

> 审计轨迹 = git 历史 + `decisions/`；不另建审计系统。

**时限怎么落地**（否则 24h / 48h 只是装饰）：登记制，不新建审批系统。
审批一挂起，当场写进 `NOW*.md` 的阻塞表（卡在谁 / 解锁条件 / 绕行，三件套齐全）；
表中的"时限"= 从登记到结论的最长时长。超时未决的，由双周回顾统一统计并升级（找上级 owner），
**同一件事不允许在阻塞表里挂过两个回顾周期**。

## 项目状态机

exploring → architecture-locked → building → frozen

- **当前状态的唯一存储位置 = `INDEX.md` frontmatter 的 `project-state`**；本节只定义状态与规则，不存状态。
- frozen 期契约冻结，只允许"最小修复"，且不得新增契约面（字段 / 端点）。
- `frozen` 期间新增 `contracts/**` 文件，由 lint 直接 fail（§9.1-11）。
- 冻结期例外决策每月回顾：例外记在 `decisions/`，且**必须同时带 `type: exception` 与 `created: YYYY-MM-DD`**。
- 缺 `created` 由 lint 判 fail；**单月 >2 次例外，强制退回 building 重新评审**（同样由 lint 计数）。
