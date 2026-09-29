# CHANGELOG

版本号唯一真源：`keel/INDEX.md` frontmatter 的 `keel-version`。
升级按该字段增量合并，**不允许"一键覆盖"**（设计稿 §12.3）。
本仓是发布仓：改动先在此发布，再更新项目仓里的子模块指针。

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