---
scope: meta
status: active
severity: P3
last-verified: 2026-10-03
triggers: 0
keywords: [死链, 冷区, 归档, NOW-history, 相对路径, 链接]
---

## 症状

把 `NOW.md` 归档到 `NOW-history/` 后，lint 报：
`❌ 死链: NOW-history/xxx.md (见 NOW-history/yyy.md)`。
可这两个文件**都真实存在**。

## 根因

死链检查按**链接所在文件的位置**解析相对路径。
归档文件本身在 `NOW-history/` 里，若链接仍带 `NOW-history/` 前缀，
拼出来就是 `NOW-history/NOW-history/yyy.md`——**多了一层目录**。

从 `NOW.md` 复制内容到归档时最容易带错：链接在热区里是对的（`NOW-history/` 是它的子目录），
搬进冷区后同一个链接就错了。

## 正解

- 归档时把链接**按所在目录重新写一遍**，别整份 cp 后就不管
- 自检：`grep NOW-history/ keel/NOW-history/*.md` 查有没有多带前缀
  有输出就是错的（冷区里不该出现 `NOW-history/` 前缀）
- 冷区不互链：只在热区文件里放真链接，归档里用纯文本指引
