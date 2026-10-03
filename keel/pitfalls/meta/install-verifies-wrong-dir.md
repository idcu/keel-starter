---
scope: meta
status: active
severity: P0
last-verified: 2026-10-03
triggers: 0
keywords: [假成功, cwd, 相对路径, 校验对象, install, 静默]
---

## 症状

`install.sh` 装到空项目后报「✅ lint 通过」、退出码 0，
但单独在那个项目里跑 lint 却是 **❌ 点火锚点缺失**。**结论相反，且"通过"是假的。**

## 根因

脚本用**相对路径**调 lint：`bash "$TARGET/keel/checks/keel-lint.sh" keel`。
但入参 `keel` 是**相对当前工作目录**解析的，不是相对脚本位置。
install.sh 通常从别处调用（下载到 `/tmp` 执行），此时 cwd 往往是**发布仓自己**——
于是 lint 校验的是发布仓（当然绿），新装项目根本没被检查。

**比"不验证"更坏**：不验证至少诚实，假成功会让人以为装好了。

## 正解

调任何接受相对路径入参的脚本前，**先 `cd` 到目标目录**：
`lintout=$(cd "$TARGET" && bash keel/checks/keel-lint.sh keel 2>&1)`

教训：第 2、4 步都用绝对路径所以对，**只有第 5 步偷懒用相对路径**。
判据：**验证步骤必须能验证到"被验证的那个对象"**。
