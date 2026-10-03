---
scope: meta
status: active
severity: P0
last-verified: 2026-10-03
triggers: 0
keywords: [参数解析, shift, 遍历中修改, ref, 静默回落, 假成功]
---

## 症状

`install.sh` 两个都在：

1. `install.sh <根> --ref v3.2.0` → `❌ 目录不存在: v3.2.0`（版本号被当项目根）
2. `install.sh <根> --ref v9.9.9`（不存在）→ **装成功了**，但装的是 `main`

## 根因

**1)** 遍历 `"$@"` 的同时 `shift`——改掉了正在遍历的集合，后面的 `while` 补救段已来不及。
**2)** ref 拉不到就**无条件回落**到默认分支，显式指定与默认跟随混为一谈。

## 正解

- 用 `while [ $# -gt 0 ] + shift`，**绝不在 `for x in "$@"` 里 shift**
- 显式 `--ref` 拉不到就**报错并列出可用版本**（判定要覆盖 `--ref v1` 与 `--ref=v1`）；
  只有「未指定」才回落

> 同一处还藏着第三个：`compliance.sh` 把 `KEEL_DIR` 写死成相对路径，被别人以不同
> cwd 调用时误报"不像 keel 目录"（第 3 步真的错了）。已改成从脚本自身位置自推。
> **凡接受相对路径入参的脚本，被别人调用时都要自己解析绝对路径。**
