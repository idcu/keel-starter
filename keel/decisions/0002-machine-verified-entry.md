---
scope: meta
status: active
last-verified: 2026-09-30
keywords: [入口, 状态, 点火, 锚点]
type: decision
created: 2026-09-30
superseded-by:
---

# 0002 入口规格进入机器验：keel-version / project-state 必填，锚点按原文检查

## 背景

v2 把"先点火"列为 P0 却没有任何检查——整套系统的开关交给了自觉；
根 INDEX 缺 keel-version / project-state 也无从判死。同类问题成片：
"写了规则却没写检查"，属于声称强制、实则空转（v3 一次补进 7 项，见 §9.1 注）。
规则只要不能被脚本判死，就等于建议。

## 决定

根 INDEX.md frontmatter 强制 `keel-version` 与 `project-state` 两字段（值域见 §5.2）；
§4.1 点火锚点必须在 CLAUDE.md / AGENTS.md / .cursorrules / .cursor/rules/keel.mdc
中出现原文，改写即 fail。两者均进入 keel-lint 检查范围（§9.1-10）。

## 被否掉的选项

| 选项 | 为什么没选 |
|---|---|
| 保持 v2：规则写在文档里，靠自觉执行 | 实测空转，且文档腐烂无人知，比没文档更危险 |
| project-state 放独立文件 | 破坏"唯一必读入口"，必读文件数与固定成本同时上升 |
| 锚点只写不检查 | 锚点是整套系统的开关，开关不能交给自觉 |

## 后果

- 好处：入口三样（协议 / 路由 / 状态）与点火开关全部可判死。
- 代价：升级方必须补 frontmatter、装锚点；锚点文案自此冻结——
  改文案等于同步改 §4.1 原文、lint 常量与各仓库锚点三处。