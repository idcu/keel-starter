---
scope: meta
status: active
severity: P2
last-verified: 2026-10-03
triggers: 0
keywords: [wc, total 行, 批量, 假 fail, 解析]
---

## 症状

预算检查改成一次 `wc -lc` 传所有文件后，报出一条假 fail：`❌ 超行数 793>160: total`。

## 根因

`wc` **多文件模式**会在末尾追加汇总行 `793 36123 total`，
按行解析时它被当成"路径为 total 的文件"，于是拿去和 `MAX_DOC` 比当然超限。
单文件模式（`wc -lc < file`）不输出 total——所以旧实现正确、批量实现错误。

## 正解

```bash
while IFS=$'\t' read -r n b f; do
  [ "${f##*/}" = "total" ] && continue      # ✅ 显式排除汇总行
  ...
done < "$tmp/sizes"
```

> 批量化不只是"少调几次函数"，它常**改变输出格式**（单文件 vs 多文件、有无 `-q`）。
> 检查清单要含一条：逐一比对单文件模式与批量模式的首行/末行/汇总行。
