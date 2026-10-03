---
scope: meta
status: active
last-verified: 2026-10-03
keywords: [坑库, 索引, shell, 性能, 批量化, 静默失效, 指标]
---

| 症状（一行，供 grep 命中） | scope | 严重度 | → 文件 |
|---|---|---|---|
| 压测下数据库连接池耗尽，接口大面积 500 | db | P1 | [db/connection-pool-exhausted.md](db/connection-pool-exhausted.md) |
| 批量化后报大量"frontmatter 缺字段"，但文件里字段齐全 | meta | P1 | [meta/xargs-arg-becomes-filename.md](meta/xargs-arg-becomes-filename.md) |
| 纯 shell 查表循环挂死不退出，栈停在字符串拆分处 | meta | P2 | [meta/command-substitution-eats-newline.md](meta/command-substitution-eats-newline.md) |
| 批量 wc 后报"超行数 N>M: total"这类以 total 为文件名的假 fail | meta | P2 | [meta/wc-total-line-treated-as-file.md](meta/wc-total-line-treated-as-file.md) |
| install.sh 报"lint 通过"但实际没验到新装项目（cwd 用了相对路径） | meta | **P0** | [meta/install-verifies-wrong-dir.md](meta/install-verifies-wrong-dir.md) |
| awk 取出的数字参与比较时按字典序比，峰值/最大值显示偏小 | meta | P2 | [meta/awk-string-vs-number-compare.md](meta/awk-string-vs-number-compare.md) |
| 手写 JSON 把空值写成 "n/a" 字符串，jq / json.load 解析失败 | meta | P2 | [meta/handwritten-json-nan-placeholder.md](meta/handwritten-json-nan-placeholder.md) |
| 归档到 NOW-history/ 后报死链，但两个文件都存在（多了一层目录） | meta | P3 | [meta/cold-zone-link-prefix.md](meta/cold-zone-link-prefix.md) |
| 文档里举例写链接语法，被 lint 判成死链 | meta | P3 | [meta/link-syntax-example-becomes-real-link.md](meta/link-syntax-example-becomes-real-link.md) |
