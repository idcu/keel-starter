---
scope: meta
status: active
severity: P1
last-verified: 2026-10-03
triggers: 0
keywords: [worktree, 行尾, CRLF, 假fail, 孤儿, 死链, 子模块, 回填]
---

## 症状

临时 worktree 里跑 lint 报一堆假 fail（孤儿 / 超字节 / 死链），
同样的内容在主工作树里却是 0 fail。

## 根因

1. `core.autocrlf=true` 时 worktree 检出成 **CRLF**，主工作树是 **LF**（任意一个都会单独触发）：
   字节虚高（实测 1181 → 1211）+ 链接目标带 `\r` → **全判孤儿**。
2. lint 的目录入参按 cwd 解析，**传绝对路径同样全判孤儿**（实测 27 条）。
3. **子模块不会被 worktree 检出**，指向子模块内文件的链接**全报死链**。

## 正解

① `git -c core.autocrlf=false -c core.eol=lf worktree add --detach -q "$wt" "$sha"`；
② `cd "$wt" && bash <lint 路径> keel`（相对入参）；
③ 把 `.gitmodules` 里的子模块从当前工作树复制进 worktree（只为让链接可解析）。

判据：**机器造出来的数，错了不会报错**——先用"已知干净"的提交做对照，
确认结果是 0 再信它。
