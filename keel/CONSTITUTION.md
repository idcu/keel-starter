---
scope: meta
status: active
last-verified: 2026-10-03
keywords: [宪法, 红线, 人审, 状态机, 两仓, 漂移]
---

# CONSTITUTION

> 这里不是"建议"，是**违反就打回**。规格见《Keel 设计稿》§5.2。
> 只放硬约束与人审关卡；其余规则一律在 INDEX.md 及其路由内。

## 身份

本项目是 **Keel**（龙骨）——AI 开发项目的上下文基座 + 轻量合规关卡。
目标：**让 AI 在任何一次会话里，都能以恒定成本拿到正确的上下文。**

- 规格唯一真源：`DESIGN.md`（本仓根）
- 代码唯一真源：`keel-starter/`（子模块，本仓不含其源码历史）
- owner：idcu
- 品牌：Keel / 龙骨；仓库名 `keel` / `keel-starter`

<!-- 这是全库唯一允许"写愿望"的地方；其余文档只写现状。 -->

## 硬约束（违反即打回）

1. **设计稿与脚本不许漂移**：本仓 `keel/checks/keel-lint.sh` 必须与 `DESIGN.md` §9.3
   的代码块**逐字一致**——`test-lint.sh` 的 DOC 检查判死不一致。改脚本必须同步改文档。
2. **子模块指针必须与发布仓 HEAD 一致**：`git submodule status` 行首不得出现 `+`。
3. **推送顺序恒为「先发布仓、后项目仓」**：反了会出现"项目仓指针指向发布仓尚不存在的
   提交"，别人 clone 直接失败。由 `scripts/release.sh --apply` 强制。
4. **项目仓自己必须用 Keel 管理**（本仓根的 `keel/` 与 `AGENTS.md` 锚点）：
   规则要求别人做而自己不做，整套论证就没有实例——锚点缺失即 lint fail。
5. **不把设计稿搬进发布仓**：`keel-starter/` 是纯模板、不含 `DESIGN.md`，
   故其 `test-lint.sh` 自动 SKIP 文档一致性检查（§12.3）。
6. **热区正文禁止出现链接语法的字面量举例**：半角 `[]()` 相邻即被判死链（§9.1-3）；
   要举例就放进 `_template*` 或冷区（坑 `link-syntax-example-becomes-real-link`）。
7. **判据与工具不得隐含假设运行环境**：行尾、PATH、解释器解析、shell 变体、**路径形态**皆算环境。
   "在我的机器上是对的"就是没验证——已踩两例（CRLF 撞字节预算、裸 `bash` 被 WSL
   垫片吃掉致自测全假失败）**同属一条病**，坑名见 `pitfalls/INDEX.md`。
   **判据必须在陌生环境复核过，自测套件尤甚**：它静默失效，项目就没了护栏。
   修法是**归一化输入**而非往判据里加过滤器；也别把"工具变安静"当"修好了"——
   安静和正确输出一样，只能靠全测分辨。

<!-- 每条都得是"能被判死"的：写不出检查方式的，不是硬约束，是愿望。 -->

## 人审关卡（AI 不得自行决定）

| 改动类型 | 审批 | 留痕 | 时限 |
|---|---|---|---|
| **改 `DESIGN.md` 的规格语义**（检查项 / 预算 / 协议原文） | owner | decisions/ + PR | 24h |
| **改 `keel-lint.sh` 的判据**（新增 / 删除 / 放宽任何检查） | owner + 双签 | decisions/ + ADR | 24h |
| **放宽预算真源 `budget.env`** | owner + 双签 | decisions/ | 24h |
| 引入新第三方依赖 | owner | decisions/ | 48h |
| 发布新版本（改 `keel-version`） | owner | CHANGELOG + decisions/ | 24h |
| frozen 期任何检查项变更 | 例外通道：双签 + 记例外 | decisions/ | 24h |

> 审计轨迹 = git 历史 + `keel/decisions/`；不另建审计系统。
> 变更 `keel-lint.sh` 属"判据变更"而非普通 bugfix——它是本项目最敏感的一类改动，
> 因为它决定"什么算错"。**判据放宽等于把过去的 fail 变成沉默。**

**时限怎么落地**（否则 24h / 48h 只是装饰）：登记制，不新建审批系统。
审批一挂起，当场写进 `keel/NOW.md` 的阻塞表（卡在谁 / 解锁条件 / 绕行，三件套齐全）；
表中的"时限"= 从登记到结论的最长时长。超时未决的，由双周回顾统一统计并升级。

## 项目状态机

exploring → architecture-locked → building → frozen

- **当前状态的唯一存储位置 = `keel/INDEX.md` frontmatter 的 `project-state`**；
  本节只定义状态与规则，不存状态。
- 当前为 `building`：v3 规格已落地并发布（v3.1.1），本仓开始按 Keel 自我管理。
- frozen 期契约冻结，只允许"最小修复"，且不得新增契约面（字段 / 端点）。
- `frozen` 期间新增 `contracts/**` 文件，由 lint 直接 fail（§9.1-11）。
- 冻结期例外决策每月回顾：例外记在 `decisions/`，且**必须同时带 `type: exception`
  与 `created: YYYY-MM-DD`**。缺 `created` 由 lint 判 fail；**单月 >2 次例外，
  强制退回 building 重新评审**（同样由 lint 计数）。
