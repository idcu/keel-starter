---
scope: meta
status: active
severity: P0
last-verified: 2026-10-04
triggers: 0
keywords: [CRLF, 行尾, 字节预算, autocrlf, 装完即红, Windows, 分发]
---

## 症状

全新 clone 到 Windows，一条命令装完、跑 lint **当场就红**：
`❌ 超字节 1211>1200`。同一个文件在 Linux/CI 上是 1181 字节，绿的。

## 根因

预算按**字节**算，而 CRLF 每行多 1 字节——字节数于是**随平台变化**。
`core.autocrlf=true` 的机器上工作树是 CRLF，CI（Linux）是 LF，
同一份内容得到两个数字。**§7.1 的字节上限隐含假设了 LF，却没有任何东西保证它是 LF。**

## 正解

在 `keel/` 里放 `.gitattributes`（`* text=auto eol=lf`）——
它随目录生效，因此跟着模板一起被复制进用户项目，继续管住字节。
**别把"每个人的 git 配置都一样"当前提。**

```bash
git check-attr text eol -- keel/INDEX.md    # 应为 text: set / eol: lf
```
