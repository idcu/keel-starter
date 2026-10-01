# CHANGELOG

版本号唯一真源：`keel/INDEX.md` frontmatter 的 `keel-version`。
升级按该字段增量合并，**不允许"一键覆盖"**（设计稿 §12.3）。
本仓是发布仓：改动先在此发布，再更新项目仓里的子模块指针。

## 3.1.0 — 2026-10-01

按"评估改进清单"依 ROI 全量推进：两个 P0 修的是**静默失效**，一个 P1 修的是**唯一没有检查形式的硬数字**。
决策记录见 `keel/decisions/0004` – `0007`。

### 1) 孤儿判定改"真实链接图"（P0，行为变更）

旧的"按文件名 grep"两头都会错：正文偶然提及会漏报，文件改名会误报。现在按**解析后的链接目标路径**判定。
**存量仓库升级后可能新报孤儿**——补一行真链接即可（ADR 0004）。回归护栏：新增用例 37。

### 2) 闭环钩子"验谎"（P0，新增 fail 面）

- lint 新增第 16 项：`checks/hooks/{pre-commit,commit-msg}` 必须存在且可执行（§9.1-16）；
- 新增 `checks/verify-hooks.sh`：额外验 `core.hooksPath` 是否挂对；CI 用 `--allow-unset`；
- `install-hooks.sh` 结尾自动复核一次——"装好了"从此不只是脚本的自述（ADR 0005）。

### 3) 单轮加载预算（P1）

`budget.env` 新增 `BYTES_SESSION=15000`（§7.2 的唯一真源）；新增 `checks/load-estimate.sh`，
把 §8 协议第 4 条从"礼貌请求"变成可执行命令（ADR 0006）。

### 4) keel-lite：裁剪成最小集（P1）

`checks/keel-lite.sh`：默认 dry-run，`--apply` 才删；连带剥离 `INDEX.md` 里对应路由行
（否则留死链），裁完自动跑 lint 复核。针对的是评估里"采用成本 4/10"这块最短的板。

### 5) MCP 只读服务 + 检索增强接入位（P2）

- `checks/mcp/keel-mcp-server.py`：把 INDEX / CONSTITUTION / NOW 暴露成 MCP resource，
  只读、零第三方依赖、自带 8 项 `--self-test`（ADR 0007）；
- `checks/check-mcp-config.sh`：校验已声明的 MCP server 可达，**恒 exit 0**（没装不算缺陷）；
- 规格见设计稿 §4.4 / §9.5。

### 6) 两仓发布编排（P3）

`scripts/release.sh`（在项目仓内）：把"先发布仓、后项目仓"这条硬约束写进脚本，
默认 dry-run，推送前自动跑发布仓 lint + 自测。

### 破坏性与迁移

| 影响 | 迁移动作 |
|---|---|
| 新增第 16 项检查 | 确认 `keel/checks/hooks/{pre-commit,commit-msg}` 存在且可执行（`chmod +x`） |
| 孤儿判定变严 | 跑一次 `keel-lint.sh`，给报出的文件补一行真链接（路由表或域索引） |
| 新增 `BYTES_SESSION` | 无需动作；要调上限只改 `budget.env` 一处 |

### 升级验收（0 fail 才算完成）

```bash
bash keel/checks/keel-lint.sh keel
bash keel/checks/test-lint.sh           # 38/38
```

### 其他

- 自测 36 例 → **38 例**（+「缺闭环钩子本体」、+「正文提及但未链接仍判孤儿」）；
- 修掉 `install-hooks.sh` / `verify-hooks.sh` 传入相对路径时前缀匹配失效的 bug；
- 新坑：`pitfalls/meta/link-syntax-example-becomes-real-link.md`（本轮自己踩的——文档里写链接语法示例会被判死链）。

## 3.0.0 — 2026-09-30

设计稿 v3 落地，**破坏性变更三项**：预算数字、frontmatter 必填字段、triggers 计数机制。
决策记录见 `keel/decisions/0001` – `0003`。

### 1) 预算：行数单约束 → 行数 × 字节 × 单行三约束

迁移：

```bash
# 工具链与预算真源以新版整体覆盖（先 diff 保留你在 rules.md 里的扩展声明）
cp -R <新版 starter>/keel/checks/ keel/checks/
bash keel/checks/keel-lint.sh keel    # 存量文档超限会逐条报出，按 §7.3 拆 / 提 / 沉
```

### 2) 根 `INDEX.md` 新增必填字段

迁移：在 `keel/INDEX.md` frontmatter 补两行：

```yaml
keel-version: 3.0.0
project-state: exploring   # exploring | architecture-locked | building | frozen
```

### 3) triggers 计数改由 commit-msg 钩子（废除"会话结束手工 +1"）

迁移（每个 clone 跑一次）：

```bash
bash keel/checks/install-hooks.sh
```

### 其他变更

- 点火锚点进 lint：AGENTS.md / CLAUDE.md / .cursorrules / .cursor/rules 缺 §4.1 原文即 fail
- 域索引（`*/INDEX.md`）只允许表格行（连注释也不行）；"怎么填"移入同目录 `_template*`
- 7 项"声称强制、实则未实现"的检查落入 `keel-lint.sh`（§9.1-2/6/7/8/9/10/11）
- MVP 并入闭环四件套：锚点 + pre-commit + commit-msg + CI（含 PR 模板）
- frontmatter 按 YAML 解析：行内注释剥离；值里禁止 `#`
- 自测 36 例：28 类 fail + 2 类告警 + 6 类合法基线

### 升级验收（0 fail 才算完成）

```bash
bash keel/checks/keel-lint.sh keel
bash keel/checks/test-lint.sh           # 36/36
```

## 2.1.0 — 首个发布

MVP 模板与五步上手（复制 `keel/` → 装钩子 → 贴 CI 与锚点 → lint 0 fail → 自测 36/36）。