---
scope: meta
status: active
last-verified: 2026-10-01
keywords: [钩子, 闭环, 验谎, lint]
type: decision
created: 2026-10-01
superseded-by:
---

# 0005 闭环钩子必须"验谎"：lint 第 16 项 + verify-hooks.sh

## 背景

§10.4 立了铁律：①②③④（锚点 / pre-commit / commit-msg / CI）缺一，强制闭环不成立。
但 v3 只把①（锚点）送进了 lint，②③ 完全没人管——于是它们有两种**静默失效**方式：

1. 钩子本体被误删、或 checkout 时丢了可执行位 → 钩子不再触发，没人知道；
2. 本体在，但 `core.hooksPath` 没挂上（**每个 clone 都要跑一次 install-hooks.sh**）→ 同样静默。

第 2 种最危险：`install-hooks.sh` 打印的"✅ 已安装"只是**脚本的自述**，不是可复核的事实。

## 决定

拆成两层，各自放在能验的地方：

- **lint 第 16 项（§9.1-16）**：`checks/hooks/{pre-commit,commit-msg}` 必须存在且可执行。进 CI，
  防的是"本体被误删"；
- **`checks/verify-hooks.sh`**：额外验 `core.hooksPath` 是否指向 `<keel>/checks/hooks`。默认语义下
  "未挂载"判 ❌；CI 用 `--allow-unset`（新 clone 天然没装）。`install-hooks.sh` 结尾**自动复核一次**。

## 被否掉的选项

| 选项 | 为什么没选 |
|---|---|
| 只在 install-hooks.sh 里 echo 一句"已安装" | 自述不等于事实；上一个会话/另一个人可能根本没跑 |
| 让 CI 也判 `core.hooksPath` | CI 是全新 clone，必然未挂载，判死等于每次都红 |
| 把钩子内容复制进 `.git/hooks/` | 不可评审、不随分支走，与 §7.4 的选择相矛盾 |
| 用 pre-commit 框架（`.pre-commit-config.yaml`） | 多一层外部依赖，违反内核零依赖 |

## 后果

- 好处：闭环第一次有了"装没装"的客观判据；安装脚本自己也被同一个尺子复核。
- 代价：**存量仓库升级后会新增一个 fail 面**——若曾把 `checks/hooks/` 删掉或没保留可执行位，lint 会红；
  修复是补回本体并 `chmod +x`（Windows 下建议 `git update-index --chmod=+x`）。
- 顺带修掉一个真 bug：`install-hooks.sh` / `verify-hooks.sh` 传入相对路径时前缀匹配会失效，已统一归一化。
