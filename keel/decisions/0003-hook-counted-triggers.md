---
scope: meta
status: active
last-verified: 2026-09-30
keywords: [triggers, 蒸馏, 钩子]
type: decision
created: 2026-09-30
superseded-by:
---

# 0003 triggers 计数改由 commit-msg 钩子自动完成

## 背景

v2 由 AI 在会话结束时给命中的坑手工 triggers +1。实测会失效：会忘、会漏，
且计数由执行者自己申报、不可验——而 triggers 是蒸馏机制的触发信号，
信号一断，§7.4 整条蒸馏链路就退化为口号。

## 决定

计数的唯一入口是提交信息：commit message 写 `pitfall: <文件名>`，
commit-msg 钩子自动 +1 并 stage，lint 只读该字段不改。
钩子本体版本化在 `checks/hooks/`，由 install-hooks.sh 设置 `core.hooksPath` 挂载（§10.4）。

## 被否掉的选项

| 选项 | 为什么没选 |
|---|---|
| 继续由 AI 手工 +1 | 不可靠、不可验；由执行者自己申报的计数没有约束力 |
| 在 pre-commit 里按 diff 猜命中的坑 | "是否命中"是语义判断，脚本无法可靠推断 |
| 靠 lint 扫文档反推触发次数 | 文档里没有"被命中"的事实，只有人工申报 |

## 后果

- 好处：计数变成提交时的机械动作，可审计（git 历史里有 message）。
- 代价：+1 要等下一次提交才落盘（git 在 commit-msg 执行前已定树，实测 2.39.5），
  对"≥3 才提醒"这类粗粒度信号无影响，但需要理解这一天延迟；
  每个 clone 必须跑一次 install-hooks.sh，否则计数静默停摆。