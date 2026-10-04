# safe-delete 垫片与路径归一化 · 完整记录（冷区）

> **发布仓版本**：本篇在Keel 项目仓（规格仓）里作为实例保留，完整踩坑经过见那里的同名文件。
> 发布仓只保留这份方法论记录——**修法已固化进 `keel-lint.sh` 的 `tmp` 归一化，
> 不依赖某条坑是否存在**。
>
> 热区结论：路径畸形 + 环境删除垫片拦截 → `pwd -P` 归一化即可，两者互不影响。

## 一、垫片的判别方法

`grep -rn "SAFE_DELETE" keel/checks/keel-lint.sh` **为空 → 噪声不是 Keel 发的**。
这条判别法来自 ADR 0014，成立。

源头在本机 PATH 前段的 `…/shim/safe-bin/rm`（WorkBuddy 的安全删除垫片）。
它有两条分支：MINGW/MSYS/CYGWIN 下检查路径是否含「内嵌盘符」，是则
`echo "[safe-delete][SAFE_DELETE_INVALID_PATH] …" >&2` 并 `return 64`。
启用门槛是 `CODEBUDDY_SESSION_ID` / `CLAUDE_SESSION_ID` 至少一个非空。

## 二、为什么 `pwd -P` 而���是 `pwd -W`

| 方案 | 输出 | 垫片 |
|---|---|---|
| `mktemp -d` 原样 | `C:\Users\ADMINI~1\AppData\Local\Temp/tmp.fNqh8Bcmea` | 拒（含盘符 + 混合分隔符） |
| `pwd -W` | `C:/Users/Administrator/AppData/Local/Temp/tmp.fNqh8Bcmea` | 放行 |
| `pwd -P` | `/c/Users/Administrator/AppData/Local/Temp/tmp.5OPNNQntDP` | 放行 |

选 `pwd -P`：**不依赖 MSYS 专有的 `-W`**（macOS 自带 bash 3.2 没有它），
POSIX 平台上 `pwd -P` 的输出本就是规范路径，行为一致。

实测对照：

```
rm -rf "$原样路径"    → rc=1（被拒）
rm -rf "$pwd -P 结果" → rc=0，目录确实消失
```

## 三、这个坑的三次演变

1. **v3.4.4**：ADR 0014 落地 NOISE 元检查，当晚抓到此前从未见过的噪声
   `[SAFE_DELETE_BULK_CONFIRM_REQUIRED]`（因判据从不检查，它"从未被见过"）。
   白名单改为前缀豁免 `SAFE_DELETE_`。
2. **v3.4.5 修前**：坑文档写的是「**不要为此改 Keel**——判据没错，改了就是迎合环境」。
   这个判断对**判据**成立，但对**泄漏**不成立：301 个目录是真损害。
3. **v3.4.5 修后**：归一化路径，判据一字未改（报错文案、语义、检查项全不变），
   只改 `tmp` 的取值方式。**stderr 与泄漏同时消失。**

## 四、附带的元教训

修"环境噪声"时我先写的一版（`tmp_posix=$(…) || tmp_posix=""` + `[ -n ]` 回退）
在 `set -u` 下偶发把路径置空，下游报 `sed: can't read : No such file or directory`
与 `syntax error near unexpected token`，**3 个自测用例连带失败**。

它长得像"环境问题"，实际是**判据自身失效**——
而这正是宪法第 7 条说的那种形态：「判据必须在陌生环境复核过」。
判死能力（能抓到真错误）与自身正确性（不因环境假设而崩）是**两件事**，
前者通过了不代表后者成立。

> 一条元规则：**只修"让 lint 变安静"的东西时，尤其要跑全量自测**——
> 因为安静和正确在输出上长得一样。