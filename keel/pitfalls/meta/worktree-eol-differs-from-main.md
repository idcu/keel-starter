---
scope: meta
status: active
severity: P1
last-verified: 2026-10-03
triggers: 0
keywords: [worktree, 行尾, CRLF, 假fail, 孤儿, 字节, 回填]
---

## 症状

临时 worktree 里跑 lint 报一大片 `❌ 孤儿` / `❌ 超字节`（实测 27 条），
同样的内容在主工作树里却是 0 fail。

## 根因

`core.autocrlf=true` 时新建 worktree 检出成 **CRLF**，主工作树是 **LF**：
字节虚高（实测 1181 → 1211，假报"超字节"）；链接目标末尾带 `\r`，
匹配不上文件清单 → **全判孤儿**。叠加第二个独立原因：lint 的目录入参
按 cwd 解析，传绝对路径同样全判孤儿。

## 正解

建 worktree 时关掉转换：`git -C "$proj" -c core.autocrlf=false -c core.eol=lf worktree add --detach -q "$wt" "$sha"`；
lint 放到该目录里用**相对**入参跑：`cd "$wt" && bash <lint 路径> keel`。

判据：**机器造出来的数，错了不会报错**——它只给一个很像真的假数字。
先用"已知干净"的提交做对照，确认结果是 0 再信它。
