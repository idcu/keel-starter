---
scope: meta
status: active
last-verified: 2026-10-03
keywords: [坑库, 索引]
---

| 症状（一行，供 grep 命中） | scope | 严重度 | → 文件 |
|---|---|---|---|
| 压测下数据库连接池耗尽，接口大面积 500 | db | P1 | [connection-pool-exhausted.md](db/connection-pool-exhausted.md) |
| 批量化后报大量"frontmatter 缺字段"，但文件里字段齐全 | meta | P1 | [meta/xargs-arg-becomes-filename.md](meta/xargs-arg-becomes-filename.md) |
| 纯 shell 查表循环挂死不退出，栈停在字符串拆分处 | meta | P2 | [meta/command-substitution-eats-newline.md](meta/command-substitution-eats-newline.md) |
| 批量 wc 后报"超行数 N>M: total"这类以 total 为文件名的假 fail | meta | P2 | [meta/wc-total-line-treated-as-file.md](meta/wc-total-line-treated-as-file.md) |
| 文档里举例写链接语法，被 lint 判成死链 | meta | P3 | [meta/link-syntax-example-becomes-real-link.md](meta/link-syntax-example-becomes-real-link.md) |
