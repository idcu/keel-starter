# CHANGELOG

版本号唯一真源：`keel/INDEX.md` frontmatter 的 `keel-version`。
升级按该字段增量合并，**不允许"一键覆盖"**（设计稿 §12.3）。
本仓是发布仓：改动先在此发布，再更新项目仓里的子模块指针。

## 3.4.5 — 2026-10-04

**一件事：把"发布后门面会漂"从一次性补正变成判据——顺便查清一个被误诊了两轮的问题。**

### 1) 新增 lint 第 17 项：版本副本一致（§9.1-17）

起因是一次**照 CI 的逻辑本地跑一遍**：

```
keel-version = 3.4.4
tag v3.4.4 存在 ✅
CHANGELOG 缺 3.4.4 小节 ❌ ← CI 在这里 exit 1（最新小节还停在 3.4.2）
```

ADR 0010 立的检查**在最近两次发布时都没守住**，两仓 README 徽章也停在 3.3.8。
这与本项目自己引用的外部证据同构：arXiv 2606.15828 记录 **Lint Leakage 占 62%**
（把 lint 本可判死的规则抄进说明书）。**判据存在却两周无人查看= 没有判据。**

新检查：`keel-version` / CHANGELOG 当期小节 / README 徽章**三者任一滞后即 fail**。
**价值不在补上这一版，在拦住下一次。**

判死能力经独立验证（不是橡皮章）：

| 场景 | 期望 | 实测 |
|---|---|---|
| CHANGELOG 缺当期小节 | 判死 | ✅ |
| README 徽章滞后 | 判死 | ✅ |
| 纯模板安装（无 CHANGELOG/README） | **跳过不误判** | ✅ |

第三条最容易漏：**"副本不存在"不能被当成"副本不一致"**，
否则所有从 `git clone` 装的用户第一屏就是红的。

### 2) 查清「分母」检索超限——**不是文档的锅，是关键词太宽**

同一批文档，不同关键词：

| 关键词 | 合计 | 判定 |
|---|---|---|
| 分母 | 17,937 | ❌ 超限 |
| 遵守率 | 12,433 | ✅ |
| 存量合规率 | 10,876 | ✅ |

「分母」多出的部分命中的是 **ADR 0014（讲自测用例计数）** 与 **JSON 坑（讲"分母为零"）**
—— **与遵守率口径毫无关系**。所以**没有拆 ADR 0014**（拆它治不了根），
改为让 `load-estimate.sh` 超限时直接打出这条诊断：先换更准确的词 →
`--list` 看清单里有无关文件就是词太宽 → 全是相关文件才是文档胖。

**没有放宽记账口径**（让 `load-estimate` 排除域索引）：那是放宽判据，违 §2 原则 4。
"命中就整篇读"与协议第 3 条一致——**保守的数字才有警戒意义**。

### 3)修 `%TEMP%` 泄漏 + stderr 首次完全干净

`mktemp -d` 在 Windows 返回 `C:\Users\…\Temp/tmp.X`——**含盘符且混用两种分隔符**，
删除垫片按规则拒绝 → `trap 'rm -rf "$tmp"'` 失效（历史堆积 301 个目录）。
改法是**归一化路径**（`pwd -P`），不是往判据里加过滤器。

**顺带揭示了一条元教训**：初版修法在 `set -u` 下偶发把路径置空，
下游报 `sed: can't read :`，**3 个自测用例连带失败**——
即"修环境噪声时自己制造了判据失效"。已上提宪法第 7 条：
**别把"工具变安静"当"修好了"，安静和正确在输出上一样。**

### 4) 新增 `keel-doctor.sh`（一键自证，只读不改）

装完跑一条命令即知自己这套 Keel 的状态：闭环门禁 / lint 结果 / 单轮加载预算 /
判据自检怎么跑 / 还差你亲手填什么。**为什么放第 0 步**：
读 README 理解价值要 30 分钟，跑一条命令看到自己的数字要 10 秒——
**价值应该可自证，而不是靠说明书说服。**

### 5) 修一个静默失效的分发缺口

`install.sh` 的就地升级是**显式文件白名单**，而新文件不在其中——
老用户升级拿不到 `keel-doctor.sh`，**且没有任何检查会报**（工具链缺失不在判据覆盖内）。

### 6) ADR 0009/0011/0012 合并为单篇口径

三篇讲同一条线（什么算分母）却各自成篇，检索"分母"会同时命中 3 篇重文档。
取证沉冷区，热区只留决策要点。发布仓「分母」检索 17,733 → **12,630✅**。

### 7) 性能基线刷新

中位 **86s**（81/89/86），余量 3.49×，散布 **1.10×**。
与 ADR 0013 修法前的 27–201s（7 倍）对比，**证明散布源于 fork 成本而非判据抖动**。

### 门禁

**41 例自测 + NOISE 元检查 + §9.3 逐字一致 = 42/42 PASS** ·
两仓 lint **0 fail 0 warn** · **stderr 0 行**

## 3.4.4 — 2026-10-04

**一件事：把「零 stderr 噪声」从一句描述变成真正会判死的判据——它第一次运行就抓到了东西。**

### 1) `NOISE` 元检查（ADR 0014，owner 已授权实施）

§9.3 一直声称自测达到"零 stderr 噪声"。但实测发现：`test-lint.py`
**捕获并打印 stderr，却全脚本没有任何一处断言它为空**——捕获 ≠ 判死。

改判据属人审关卡（owner + 双签）。owner 明确授权
（"全部给你授权，按你的分析拍板并全量推进"），故本版落地，
**授权来源与范围写进 ADR 0014 正文**，未借授权扩大范围。

**第一次运行就抓到此前从未见过的噪声**：`[SAFE_DELETE_BULK_CONFIRM_REQUIRED]`。
它"从未见过"正因为判据从不检查——**缺口一补就显示下面还压着别的东西**。

- 白名单改为**前缀豁免** `SAFE_DELETE_`（同源同因同解，不逐条枚举）
- **豁免必打印**，白名单一旦静默就等于没有判据
- **独立验过判死能力**：真错误（`can't open INDEX` / `awk:`）确实判死，非橡皮章

> 登记一个诚实边界：这条判据管的是"**未豁免的**stderr 噪声"。
> 本机 safe-delete 垫片那行`SAFE_DELETE_INVALID_PATH` 是**宿主环境**发的
> （`keel-lint.sh` 内零命中），白名单是**判据不是滤器**——它让自测判PASS，
> 但不过滤 lint 进程的 fd 2。手跑 lint 仍会看到那一行。

### 2) 蒸馏告警不再报已蒸馏的坑

段 11 只看 `triggers` 不看 `status`，而 §7.4 的流程
「triggers≥3 → 提炼 + 置 `distilled`」**永远走不到终点**：
坑都蒸馏完了，告警还在报。

实测：造 `active` / `distilled` 两条样本，只报 `active` 的。**那条挂了许久的 ⚠️ 终于消失。**

### 3) 顺带修一个判据自曝的计数 bug

输出曾成`39/38 例`（加了元检查但分母没跟着变），现显式写作 `38 用例 + 1 元检查`。

**39/39 自测 PASS · §9.3 逐字一致 · 两仓 lint 0 fail · 零 ⚠️**

## 3.4.3 — 2026-10-04

**一件事：实测出一处判据的能力上限，并如实写进规格——不改判据，只标边界。**

### 1) `check-mcp-config` 的五个边界 + 一处能力上限

五个边界全部实测，**均正确处理**：无声明 rc=0 / command 不在 PATH 正确报 /
JSON 坏 / `mcpServers` 空 / 缺 `command`。

但查出一处上限：`{"command":"bash","args":["-c","exit 7"]}` 被判 ✅ 全部可达，
**实际 rc=7**——

> **判据只证"可执行文件存在"，证不了"server 能启动"。**

这不是实现 bug，是**规格的能力上限**：MCP server 是 stdio 子进程，
真要验"能起来"得把它拉起来发一次 `initialize`，
超出 lint 该干的范围（要超时保护、防挂住 CI）。

**处理**：未改判据，把边界写进 §9.5 + 登记 P3 坑 `check-mcp-config-only-proves-path`。
「没装 Serena」绝不算项目缺陷，该项刻意定为 ⚠️ warn 而非 fail。

### 2) `pitfalls/INDEX.md` 按 §7.3 重整

15 条坑的症状列削到**"最短可 grep 特征"**——细节留在坑文件里，索引不复制正文
（§2 原则 1：每类事实只有一个定义位置）。索引 **3139 → 2993 字节**（限额 3000）。

**一条方法论**：能力边界值得写进规格，因为**没写就等于没人知道这条判据不管什么**。
判据能过 ≠ 判据正确；把"它证不了什么"显式记下来，下一个人才不会误以为它万能。

## 3.4.2 — 2026-10-04

**一件事：把剩下没测过的工具全跑一遍——真实新用户流程端到端验证 + 段 11 批量化。**

### 1) 端到端跑通"克隆 → 装 → 提交"

从 v3.4.1 tag 克隆后模拟新用户，逐项实测：

| 步骤 | 结果 |
|---|---|
| `install.sh .`（无锚点） | **rc=1** + 给出可操作提示（协议在门内，钥匙必须在门外） |
| `install.sh . --with-anchor` | **rc=0**，锚点写入 `AGENTS.md`，钩子挂上 |
| 重跑 `--with-anchor` | **幂等**，`AGENTS.md` 内容未变 |
| 故意提交超字节文件 | **❌ 提交已拦下** + 自动记入遵守率（"绕过不会让它消失"） |
| `verify-hooks`（已装 / 卸掉） | ✅ 就绪 / **rc=1「闭环此刻是静默失效的」**；`--allow-unset` 正确容忍 |
| `compliance backfill` / `report` | 出存量合规率；遵守率 **50%**（1 次真实拦截计入） |
| `reset`（裸） | 明确警告"含实时遵守率且无法重建"，并指向 `--backfill` |
| `reset --backfill` | 精确只清 1 条回填，**保留 5 条实时记录** |

**结论：闭环在真实项目里成立**，不是只在本仓自测里成立。

### 2) 段 11 三段式批量化（ADR 0013 第三项，上一版试过并回退）

上一版的失败原因已查明并登记（坑 `awk-enfile-ignores-skip-state`）：
`ENDFILE` **不受 `skip` 状态约束** → 39 个非坑文件误报、12 条真坑漏判。

这次的做法是**把过滤与判断分开**：
1. **过滤在 shell 侧**：纯 `case` 判 `pitfalls/*` 与豁免项，**零 fork**，落成清单；
2. **判断在 awk 侧**：一次 awk 扫全部，用 **`FNR==1` 切文件 + `END` 收尾**——
   这是 `ENDFILE` 的**可移植替代品**（POSIX awk 即可，不依赖 gawk 扩展）。

**验证**：造一个缺【## 正解】的坑，**新旧两版输出逐字相同**；38/38 自测全 PASS。
**64s，预算余量 4.69×**（ADR 0013 三项优化至此全部落地）。

### 3) ADR 0014（**提案，待双签**）："零 stderr 噪声"目前只是一句描述

§9.3 声称自测达到"零 stderr 噪声"。实测：`test-lint.py` **捕获并打印 stderr，
但全脚本没有任何一处断言它为空**——捕获 ≠ 判死。

而本机 lint 每次都有一行 stderr（`[SAFE_DELETE_INVALID_PATH]`，已查明非 Keel 所发），
**38 例全 PASS 却无人发现**。若某天 lint 真的开始吐真错误，同样不会有任何东西发现。

**本版刻意不动判据**（改判据需 owner + 双签，且要连带同步 §9.3 与发版）。
只把实施要点、豁免白名单设计与风险写进 ADR 0014，等签署。

## 3.4.1 — 2026-10-04

**一件事：把三个"从没被真正跑过"的工具逐个实测——查出两个真 bug。**

上一版把性能优化做完了，但仓库里还有一批脚本**随模板分发却从未被验证过**。
本轮把它们逐个跑了一遍，结果不如预期但价值很大。

### 1) `keel-lite.sh --apply` 会把项目弄红（P0 级）

从干净 clone 实测（39 个 md → 裁剪后 19 个）：

```
⚠️ 裁剪后 keel-lint 未通过
   ❌ 孤儿: CONSTITUTION.md / NOW.md / checks/rules.md / pitfalls/… （6 个）
```

**顺序错**：脚本先删目录、再剥 `INDEX.md` 的路由行。而 §9.1-4 的孤儿判定
**只豁免 `INDEX.md` 与 `_template*`** —— INDEX 一旦不再链接其余文档，
**每一个热区文档都成了孤儿**，脚本 `exit 1`。

**用户视角**：照 README 跑一条"裁剪到最小集"的命令，**结果项目直接变红**。
而它本该降低采用成本（这是评分最低的一块板，4/10）。

修法：**先算好新 INDEX → 再删目录 → 最后替换 INDEX**。
实测裁剪后 `keel-lint` ✅ 通过（5s）。

### 2) MCP 服务的版本号硬编码，已落后三个版本（P1）

`keel-mcp-server.py` 里 `SERVER_VERSION = "3.1.0"` 是写死的常量。
到 v3.4.0 时，**MCP 客户端看到的版本与实际装到的版本对不上**——
而 §2 原则 1 说"每类事实只有一个定义位置"。

改为从 `INDEX.md` 的 `keel-version` 读；**读不到时显式报 `0.0.0-unknown`**——
宁可说不知道，不报一个假版本。实测 `serverInfo.version` 正确返回 `3.4.0`。

（顺带确认：MCP 内置自测 **8/8 PASS**，`check-mcp-config.sh` 未声明检索增强时恒 exit 0。）

### 3) `to_epoch` 纯 shell 化：65s

上一版留下"每次跑两次 `date`"（先试 BSD `-j -f`，在 Linux/Git Bash 上必然失败，
再试 GNU `-d`，每次 ~250ms）。改用 Howard Hinnant 的 `days_from_civil`
（公历恒等式，无闰年特殊分支，**零 fork**）。

**验证**：对 23 个日期与 `date -u -d` **逐字对照**，含 1900/2100 非闰年世纪、
2000/2024 闰年、1600/9999 边界；非法输入（`2026-13-01` 等）全部拒绝。
再用同一 fixture 跑新旧两版，输出**逐字相同**（`stale(2468d)`）。

**单次 lint 68s → 65s，预算余量 4.35× → 4.62×。**

### 一条方法论

本轮三个 bug 形状相同：**代码"看起来在正常工作"，实际从未被运行过**。
与 v3.3.9 修的自测套件同族——**没跑过的代码等于不存在的代码**，
而它的失败方式还是"报一个看起来合理的错"。

## 3.4.0 — 2026-10-04

**一件事：把 `$(纯 shell 函数)` 的 ~1,170 次 fork 干掉——单次 lint 从 142s 到 68s。**

### 1) 慢的不是判据，是命令替换本身

上一版查清了"7 倍抖动"的根因是 fork 成本（ADR 0013），但当时只解释、没动手。
本轮做第一项优化，结果比预期好得多，因为找到了**更深一层**：

| 写法 | 每次成本 |
|---|---|
| `v=$(pure_shell_fn)` | **~100ms** |
| 直接调用（不取返回值） | ~0ms |
| 函数内写全局变量 + 读它 | ~0ms |

**`$(纯 shell 函数)` 本身就要开一个子 shell——与函数体内有没有外部命令无关。**
ADR 0008 消掉的是"真外部命令"的 per-file 调用（那部分确实做到了），
但 `st=$(fmq …)`、`rel=$(rel_of …)` 这种**取返回值**的写法自带一个 fork。

全脚本 30 个 `$(rel_of|basename|fmq|…)` 站点 × 39 文件
≈ **1,170 次 fork ≈ 117s**——**占 142s 的大头**。

修法：加 `rel_set` / `base_set` / `fmq_set` 三个零 fork 版（结果写 `REL`/`BASE`/`REPLY`），
30 个站点全换。**语义、判据、报错文案一字未改，只换传值方式。**

**实测 142s → 68s（2.1×）；预算余量从 1.68× 回到 4.35×。**
38/38 自测全 PASS、`DESIGN.md` §9.3 逐字一致——**护栏证明没动语义**。

### 2) `perf-baseline.sh`：让"省了多少"有客观记录

以前每次优化只能靠"感觉快了"。现在重复采样并输出中位/极值 + 预算余量，
阈值从 `budget.env` 读（不复制数字）。附带一条判断：中位用掉预算一半以上时
该做优化了。

### 3) 一次失败的尝试，以及它为什么该失败

第三项优化（批量化段 11 的三段式检查）**试过并回退了**：
改成"一次 awk + `ENDFILE`"后，`ENDFILE` 规则**不受 `skip` 状态约束**——
**39 个非坑文件全被报"缺三段式"，12 条真坑一条不报**。方向完全反了，
而且输出看着"合理"，只有对照文件清单才发现。

收益只有 3.6s，不值得引入一类新的误判。已登记为坑 `awk-enfile-ignores-skip-state`。
**语义优先于速度**——ADR 0013 的原则。

## 3.3.9 — 2026-10-04

**一件事：那个"验证 lint 本身"的套件，在 Windows 上一次都没真跑过。**

### 1) 自测套件 38 例全假失败（P0）

`keel/checks/test-lint.py` 用**裸 `"bash"`** 调子进程：

```python
p = subprocess.run(["bash", LINT, "keel"], cwd=cwd, ...)
```

Windows 上 Python 的 `subprocess` 与 `shutil.which` 解析规则不同：

| 解析方式 | 命中 | 行为 |
|---|---|---|
| `subprocess.run(["bash", …])` | `C:\Windows\system32\bash.exe` | **WSL 垫片**：打印安装提示后 exit 1 |
| `shutil.which("bash")` | `…\PortableGit\…\usr\bin\bash.EXE` | 真正的 Git Bash |

于是 38 次调用全部拿到同一段 95 字节的 WSL 提示，断言「期望命中某检查项」自然全落空：

```
[FAIL] 00 合法基线 MVP 全绿   期望=无 ❌ 实际=干净  退出码=1（期望 0）
       （无任何 ❌/⚠️ 输出）
```

**它报的是"未通过"而不是"环境异常"，所以看起来像判据坏了——而判据是好的。**
最硬的证据是耗时：修复前"秒级返回"，修复后 **19–24 分钟**。这才是 38 次真实调用的成本。

> 换句话说：项目自己的护栏曾经失效 24 小时无人察觉，而套件还在报告"失败"。
> **最危险的不是判据坏了，是护栏坏了却在报"成功"。**

修法一行（`shutil` 早已 import）：

```python
bash = shutil.which("bash") or "bash"
p = subprocess.run([bash, LINT, "keel"], cwd=cwd, ...)
```

**实测：38/38 PASS，含 DOC「与 DESIGN.md §9.3 逐字一致」。**

同类问题的第二例是 v3.3.8 修的 CRLF 撞爆字节预算——那次是把**行尾**交给每个人的
git 配置，这次是把 **bash 解析权**交给每个人的 PATH。同一类病，因此已上提为
宪法硬约束第 7 条：**判据与工具不得隐含假设运行环境**。

### 2) 「遵守率」曾经读不起（它才是最终目的）

`load-estimate.sh 遵守率` 实测 **17,940 > 15,000**（上轮还是 14,665，余量仅 335）。
成因是上一轮自己的修复：ADR 0009 瘦身 −147 字节，同轮新增的 ADR 0011 却是 +3,175。

按设计稿 §7.3「拆 / 提 / 沉」处理——脚本清单沉入冷区 `archive/script-inventory.md`，
ADR 0009 去掉与 `docs/research/` 重复的取证段，ADR 0011 收敛失效模式段
（改为指向已登记的坑）。**结果：`遵守率` 14,139、`分母` 14,977、`度量` 8,457，全部回到限额内。**

> 值得记的是：最该被频繁读取的那个指标，恰恰先被自己挤出了预算。
> 存量不是问题，**"把话又说一遍"才是**——ADR 0009 删掉的都是 research 文档里已有的。

### 3) 性能抖动的根因查清了（不是判据，是 fork）

连续采样散布 **27s / 31s / 137s / 145s / 178s / 184s / 201s = 7 倍**，
而 `LINT_SECONDS=300` 注释里的"97–193s"依据已与现实脱节。连续两轮登记为"未查明"，
本轮用**分段打点 + 微基准**定位（`N=20`，Git Bash）：

| 操作 | 每次成本 |
|---|---|
| 纯 shell 赋值 | **~0ms** |
| `$(printf …)` | ~50ms |
| `$(basename …)` | ~150ms |
| `date -d` | **~250ms** |

分段打点：段 3 值域 **41s**、段 4 命名 **24s**、段 11 坑条目 **24s**、段 10 陈旧 **10s**
——**没有单点热点，是 per-file 小命令成本 × 文件数**。ADR 0008 的批量化已把
段 1/2/6/8/9 做完，剩的是 `$(basename)` / `date` 这类。

**不是并发**（静默态复现 140s），**不是判据复杂**（Linux CI 3–8s）。
本版**不改判据、不抬 `LINT_SECONDS`**——300s ≈ 最差值的 1.5 倍，余量已很薄，
抬阈值只是让告警更晚触发。优化路径记在 ADR 0013，留给后续单独立项。

## 3.3.8 — 2026-10-04

**两件事：新用户在 Windows 上"装完即红"（P0），以及把第 1 步的摩擦降到可选。**

### 1) 字节预算默认了 LF——CRLF 下当场撞爆（P0）

全新 clone 到 `core.autocrlf=true` 的机器，装完跑 lint **立刻红**：

```
❌ 超字节 1211>1200: pitfalls/meta/arg-parse-shift-while-iterating.md
```

同一个文件在 CI（Linux）上是 **1181 字节，绿的**。差别就是每行多出来的 1 个 `\r`。

**§7.1 的字节上限隐含假设了 LF，却没有任何东西保证它是 LF**——
而这一屏恰好是新用户看到的第一屏，也是最不该红的一屏。

修法不是"把那个文件改短"，而是**把行尾交给机器**：
在 `keel/` 里放 `.gitattributes`（`* text=auto eol=lf`）。
放在 `keel/`（而非仓库根）是关键：gitattributes 随目录生效，
于是它跟着模板一起被复制进用户项目，**继续管住那些字节**。

审计结果（CRLF 下会撞限的文件）：`pitfalls/_template.md`、
`pitfalls/meta/arg-parse-shift-while-iterating.md`——均已留出余量；
另有 5 个贴到 90%+，靠 `.gitattributes` 兜住。

### 2) `install.sh --with-anchor`：第 1 步可以不用手抄

装完还差三步，第 1 步"贴锚点"是最大的流失点：不贴，lint 当场判死、
install.sh 以非零退出，新用户看到的是"装失败了"。

现在加 `--with-anchor` 就由我写进 `AGENTS.md`：文件不存在则创建，
已存在则**追加到末尾、一行不动你原来的内容**，已经有锚点则什么都不做（幂等）。

**默认仍然是关闭**——未经允许改用户的 `AGENTS.md` 是越界；
不加开关时脚本只提示这一行怎么加。

### 升级验收

```bash
bash keel/checks/keel-lint.sh keel
bash keel/checks/test-lint.sh                    # 38/38
git check-attr text eol -- keel/INDEX.md         # 应为 text: set / eol: lf
```

## 3.3.7 — 2026-10-03

**`reset` 会误删遵守率的真实记录——加一个定向的 `reset --backfill`。**

### 为什么必须加

重跑 `backfill` 前要先清掉旧的回填记录，最自然的动作是 `reset`。
但裸 `reset` 是**无差别清空**，会把实时遵守率的记录一起删掉——
而那些记录**只由 pre-commit 产生，删了无法重建**（实测就这么丢过一轮已累积的数据）。

```
reset             # 全清：换基线时用（会删掉遵守率，且无法重建）
reset --backfill  # 只清回填记录：重跑 backfill 前用这个
```

命令自己的输出也会把这句警告打出来，避免"想刷新存量合规率，结果把遵守率清了"。

### 升级验收

```bash
bash keel/checks/keel-lint.sh keel
bash keel/checks/test-lint.sh                    # 38/38
bash keel/checks/compliance.sh reset --backfill  # 应显示"保留 N 条实时记录"
```

## 3.3.6 — 2026-10-03

**修 v3.3.5 刚发布的 `backfill`：在带子模块的仓库里，每个提交都假报 1 条死链。**

### 子模块不会被 worktree 检出

`git worktree add` **不检出子模块**，于是子模块目录是空的；
任何指向子模块内部文件的链接（本项目实例就是 `../keel-starter/keel/INDEX.md`）
都会被判死链。实测：项目仓 12 个提交**每个都恰好 ❌ 1**，整齐得不正常——
**"整齐"本身就是假 fail 的特征**。

修法：回填时把 `.gitmodules` 里声明的子模块从当前工作树复制进临时 worktree。
填的是**占位**（让链接可解析），不是结论——死链判的是"文件在不在"。

连同 v3.3.5 一起发现的另外两个成因已并入坑条目
`meta/worktree-eol-differs-from-main.md`：行尾 CRLF、lint 传绝对路径入参。

> 三处都是同一类教训：**机器造出来的数，错了不会报错**。
> 所以 `backfill` 这类路径必须先用"已知干净"的提交做对照，确认是 0 再信它。

### 升级验收

```bash
bash keel/checks/keel-lint.sh keel
bash keel/checks/test-lint.sh                    # 38/38
bash keel/checks/compliance.sh backfill --max 2  # 已知干净的提交：❌ 应为 0
```

## 3.3.5 — 2026-10-03

**新增 `compliance.sh backfill`：装完第一天就能看到第一个数。**
以及修掉一条**守卫自己撒谎**的 CI 断言。

### 回填历史提交（ADR 0011）

遵守率唯一的硬伤是**没有基线**——它从装上钩子那一刻才产生数据，要等几周。
于是自然会想到"用 git 历史回填造出基线"。**技术上做得到，但这个基线是假的**：

> 遵守率的分母是"门禁有机会拦的次数"；装上钩子之前的历史提交**根本没有门禁**，
> 分母不存在。把它们算进分母，等于宣称"这些提交当年被检查过"。

所以回填产出的是**另一个数——存量合规率**，带 `backfill=1`，**不进遵守率的分母**，
只在报告里单列一段。它回答的是：**「仓库现存内容，按今天的判据看有多干净」**。

```bash
bash keel/checks/compliance.sh backfill --max 10 --dry   # 先看会跑几个
bash keel/checks/compliance.sh backfill --max 10         # 真跑（每个提交一次完整 lint）
bash keel/checks/compliance.sh report                    # 两个数：遵守率 + 存量合规率
```

诚实说明它的适用边界：**在已经用 Keel 管住的仓库里，它会接近 100%**——
存量早被门禁筛过一遍，信息量低。它真正的用武之地是"刚装完、历史从未被门禁管过"的仓库，
也就是**新用户的第一天**。

### 修一条撒谎的 CI 断言（P1）

`keel.yml` 里"基线排除"那条自检断言 `"rounds":0`，**但实现返回的是 2**
——前面还留着两条真实记录。基线**确实**被排除了（分母没被污染），
**错的是断言**：它验的是别的东西，于是一条本该守住口径的检查长期不知道自己没在守。

修法：断言前先 `reset`，再只记一条基线。另加一条 `backfill --dry` 自检
（`--dry` 若偷偷写了记录，遵守率会被历史污染）。

### 新坑一条（本轮自己踩的）

`meta/worktree-eol-differs-from-main.md`（**P1**）：临时 worktree 在
`core.autocrlf=true` 下检出成 CRLF，而主工作树是 LF——
字节虚高（实测 1181→1211，假报"超字节"）+ 链接目标带 `\r` 全判孤儿（实测 27 条假 fail）。
叠加第二个独立原因：lint 的目录入参必须传**相对**的 `keel`（传绝对路径同样 27 条假 fail）。

**这类"机器造数"的路径错了不会报错，只会给出一个很像真的假数字。**

### 升级验收

```bash
bash keel/checks/keel-lint.sh keel
bash keel/checks/test-lint.sh                    # 38/38
bash keel/checks/compliance.sh backfill --max 3 --dry
bash keel/checks/compliance.sh report
```

## 3.3.4 — 2026-10-03

**补齐 v3.2.0–v3.3.3 的 tag；修 install.sh 两个 P0（版本固定形同虚设）。**

### 补 tag（P0）

`keel-version` 一直升到 3.3.3、CHANGELOG 也写全了，**但 git tag 只到 v3.1.1**。
后果不是"少了几个标记"，而是：

- `install.sh --ref v3.2.0`（README 亲口教用户这么用）**直接失效**；
- 用户无法固定版本，只能跟着 `main` 走——**分发渠道最要紧的能力是缺的**。

已补 v3.2.0 / v3.3.0 / v3.3.1 / v3.3.2 / v3.3.3 五个 tag 并推送，
8 个 tag 的 `keel-version` 与 tag 名逐一核对一致。

### 修 install.sh 参数解析（P0）

```bash
for a in "$@"; do
  case "$a" in --ref) shift ;; ...   # ← 遍历途中改掉了 "$@"
```

`install.sh <根> --ref v3.2.0` 会把 `v3.2.0` 当成项目根（实测报「目录不存在: v3.2.0」）。
改为 `while [ $# -gt 0 ] + shift` 逐个取。

### 修静默回落（P0）

`--ref v9.9.9`（不存在）会**静默装上 `main`**——用户以为固定了版本，
实际拿到别的东西，**比直接失败更坏**。现在显式 `--ref` 拉不到就报错并列出可用版本；
只有「未指定」才允许回落。判定覆盖 `--ref v1` 与 `--ref=v1` 两种写法。

### 顺带

- `compliance.sh` 的 `KEEL_DIR` 改为从脚本自身位置自推绝对路径
  （写死相对路径 `keel` 时，被 install.sh 以别的 cwd 调用会误报"不像 keel 目录"）
- 新坑 `meta/arg-parse-shift-while-iterating.md`（**P0**）

> 这一版的共同教训：**"版本号写对了"不等于"版本能用"**。
> 声明（`keel-version` / CHANGELOG）与可获取（tag / 分发）必须一起验。

## 3.3.3 — 2026-10-03

**首次安装不再污染指标基线；并修一个手写 JSON 的合法性 bug。**

### 首次安装记基线（P1）

`install.sh` 装完会记一条 `baseline=1`。它**不计入遵守率的分母**——
装模板不是"一次工作"。否则新用户第一次跑 `compliance.sh report`
会看到 `files=50, md=33` 的初始化噪声，被当成"我刚装完就一堆问题"。

`report` 会显式说明排除了几条基线记录。

### 修手写 JSON 的 `n/a`（P2）

`report --json` 在无数据时输出 `"rate":"n/a"`（**字符串**），
`jq` / `json.load()` 解析会失败。**JSON 没有 NaN/NA，只有 `null`**。

改为分两份：给 JSON 的用裸 `null`，给终端看的用 `—`。
CI 已加断言：仅有基线时 `rounds` 须为 0、`rate` 须为 `null`。

### 端到端验证了公网分发链路

从 `gitee.com/.../raw/main/install.sh` 真拉一次装到空项目：
URL 302 → 跟随后 7086 字节完整脚本 → clone `https://` 可通 → 装成功
→ 正确判出锚点缺失并给出指引 → 补锚点后 lint 转绿 → 提交触发钩子并产出数据。

**此前所有验证都把 `REPO` 换成本地路径，从没验过公网那一段。**

### 顺带

- `install.sh` 的就地升级清单补上 `compliance.sh`
  （漏了它，老用户升级后就没有基线记录能力）
- 新坑：`meta/handwritten-json-nan-placeholder.md`（P2）

### 升级验收

```bash
bash keel/checks/keel-lint.sh keel
bash keel/checks/test-lint.sh                    # 38/38
bash keel/checks/compliance.sh report            # 新装应为 rounds=0
```

## 3.3.2 — 2026-10-03

**把遵守率的分母补全，并新增覆盖率指标。** 上一版修了分子（补回滚），这一版修分母。

### 分母补全（P0）

原守卫是 `grep -E "^keel/.*\.md$"`（本意只是不白跑 lint），但副作用是
**只改代码的提交完全不进分母**——而"改 contracts 却没同步 INDEX"这类违规
恰恰最容易发生在纯代码提交里，于是它成了指标的盲区。

**实测确认漏洞**：干净仓里提交一次只改 `.py` 的改动 → `violations.jsonl` **0 条记录**。

现拆成两件事：

| | 做什么 | 成本 |
|---|---|---|
| **记录** | 所有提交都记（只用 `git diff`） | 廉价 |
| **校验** | 只有 keel 下 md 变了才跑 lint | 昂贵，且此时才有意义 |

记录里新增 `checked=0/1` 与 `md=N` 两个字段。老记录没有 `checked` 时按 `checked=1`
处理，向后兼容。

### 新增覆盖率指标

```
覆盖率 = 跑过 lint 的提交数 / 全部提交数
```

**必须与遵守率一起读**。未检查的提交计入分母、不计入分子，所以覆盖率低会让遵守率
**偏低**——真正的风险是「**覆盖率低 + 遵守率高**」：大量提交根本没被检查，高分是假的。
`report` 会同时打出两个数，并在输出里写明这一点（提醒从 4 条增到 5 条）。

### 顺带

- 本仓（keel 规格仓）**装上了钩子**——此前 15 次提交从未触发过 pre-commit，
  指标数据一直是空的。现从提交开始产生真实数据。

### 升级验收

```bash
bash keel/checks/keel-lint.sh keel
bash keel/checks/test-lint.sh                    # 38/38
bash keel/checks/compliance.sh report            # 注意看「覆盖率」那一行
```

## 3.3.1 — 2026-10-03

按调研报告（`docs/research/context-governance-verify.md`）§5.2/§5.3 修正遵守率口径，
并给分发入口加 CI 验证。**修了两个"看起来对、其实错"的 bug。**

### 1) 遵守率补回滚维度（口径修正，P0）

初版只记「lint 命中」，**漏了放行后被回滚的提交**——而那恰恰是 lint 自己看不见的
一类不遵守：门禁说通过、提交成功，之后才被推翻。

```
遵守率 = 1 − (lint 命中轮次 + 放行后被回滚数) / 总检查轮次
```

**实测差异（同一假仓：三轮记录 + 一次真回滚）**：66.7% → **33.3%**，**虚高一倍**。
口径错一点，整个数字就没意义。

匹配用 `git log --grep='^Revert "'`（git 自动生成的精确格式）。
**不要用 `-i --grep=revert`**——实测会把"实现 revert 按钮的功能"误计。

### 2) 预算超限率聚合（P1）

`load-estimate.sh` 每轮写 `load.jsonl`（含 `over=0/1`），报告一并给出超限率。
它测的是"上下文基座够不够用"，与遵守率正相关但**不是一回事**：
遵守率低 → AI 不守规矩；超限率高 → 基座装不下该装的东西。

对比 aegis：它超限时把文档**降级为 deferred**，AI 并不知道哪部分被降级，
会基于残缺上下文自信作答；Keel 超限即报错，更强——但要把它变成可度量信号。

### 3) 修 P0 假成功：install.sh 的校验没验到新装项目

`install.sh` 用相对路径 `keel` 调 lint，而该入参是**相对 cwd** 解析的。
install.sh 通常从别处调用（下载到 `/tmp` 执行），此时 cwd 往往是**发布仓自己**
——于是 lint 校验的是发布仓（当然绿），新装项目根本没被检查。

**比"不验证"更坏**：不验证至少诚实，假成功会让人以为装好了。
修法：`cd "$TARGET" && bash keel/checks/keel-lint.sh keel`。

顺带修：install.sh 原来把 lint 输出丢 `/dev/null` 只说"未通过"，
现在打印判死原因，并对锚点缺失给出具体指引。

### 4) install.sh 进 CI（P1）

之前 CI 全在 starter 仓内自检，**装到别的项目里能不能用，一句都没验**。
新增端到端冒烟：空项目 → 装 → 钩子 100755 → 锚点判死 → 补上转绿。
另加遵守率口径自检（回滚必须计入分子）。四步均本地实测后才写进 workflow。

### 5) 修两个自己引入的问题

- **发布仓索引回归**：误把项目仓实例的 `pitfalls/INDEX.md` 覆盖到发布仓，
  挤掉了模板原有的连接池坑登记 → 发布仓 lint 报 2 条 fail。已修。
- **awk 字符串比较**：`v > max` 走字典序，**峰值永远显示偏小**（18999 < 6000）。
  判据：凡从文本抽出的数字参与比较，必须显式 `+0` 转数值。

### 新坑两条

- `meta/install-verifies-wrong-dir.md`（**P0**）
- `meta/awk-string-vs-number-compare.md`（P2）

### 升级验收

```bash
bash keel/checks/keel-lint.sh keel
bash keel/checks/test-lint.sh              # 38/38
bash keel/checks/compliance.sh report      # 遵守率（口径已含回滚）
```

## 3.3.0 — 2026-10-03

**遵守率：全赛道无人实现的那个指标**（设计稿 §11.2 / ADR 0009）。

### 为什么它是空白的（2026-10 逐个读源码核实，非读 README）

| 项目 | 体量 | 它的"遵守率" | 判定 |
|---|---|---|---|
| `dsh-rule-lens` | 1485 行 JS / 3 提交 / 零测试 | 面板写"遵守率"，但**只有拦截计数、没有分母** | **数字方向是反的** |
| `aegis` | 41k 行 TS / 989 测试 | adapter 规则第 5 步 "Self-Review" | **AI 自报 = 不可验** |
| `holaOS` | 48 万行 TS | 全仓 grep → 零实现 | 干脆没做 |

而 holaOS 的一份 223 行取证文档给出了关键反例：
**门禁全部正确触发、AI 对目标目录零编辑、然后宣布完成**；
它试过加重门禁措辞 → 得到**更精致的形式合规**。

### 口径

```
遵守率 = 1 − (至少命中一条检查项的轮次 / 总轮次)
```

数据源**全客观，AI 一个都改不了**：
- `fails` / `warns` ← 从 `keel-lint.sh` 的真实输出数出
- `files` ← `git diff --cached`

**故意不按"命中条数"算分子**：一次提交踩 3 条和踩 1 条，对"这轮守没守规矩"
是同一件事。按条数算会让数字随检查项数量漂移——加一条检查项就能让历史遵守率"变差"。

### 新增

- `checks/compliance.sh`：`record` / `report [--json]` / `reset`
- `pre-commit` 改造：**先记再判**——故意违规的那次也留痕，
  否则"刻意绕过"会变成指标盲区，而那恰恰最该被看见
- `.gitignore` 排除 `keel/checks/.metrics/`（本机观测数据，不进版本库）

### 破除性提醒：这个数字会骗人

1. **遵守率低先查规则是否可遵守**（§2 原则 4），不是先怪 AI
2. 只量「提交时的合规」，没改 md 的提交不计入分母
3. **没有基线就没有意义**——第一次的数字别当成绩

### 顺带一条反直觉发现（已改 `pitfalls/_template.md`）

> **在规则里点名失败模式，AI 会精确复现那个失败模式。**

所以「正解」段必须写**具体动作**（"连接走全局单例，在 DAO 构造函数注入"），
不能写"不要在循环里建连接"——后者会让那个组合更显著。

### 升级验收

```bash
bash keel/checks/keel-lint.sh keel
bash keel/checks/test-lint.sh              # 38/38
bash keel/checks/compliance.sh report      # 遵守率（需先有提交记录）
```

## 3.2.0 — 2026-10-03

按《KEEL-评估报告-20261003》的 P0/P1 项整改。**检查结论完全不变，
改的是"跑得慢"和"两处真实 bug"**。决策记录见 `keel/decisions/0008`。

### 1) `keel-lint` 性能：319s → 97s（同为 24 个热区文档，降 70%）

根因不是逻辑复杂，而是**进程创建成本**：单次 fork 在 Windows/Git Bash 约 370ms，
原实现有约 1500 次 per-file fork。

| 改动 | 效果 |
|---|---|
| 预算段 `wc` 批量化（`xargs -0 wc -lc`） | 16.1s → 0.52s（31×） |
| frontmatter 一次 awk 抽全部字段落查询表 | 替代 `fm_val` 的 4 fork/次 |
| 链接提取一次 awk，段 6/8/9 共用 | 段 9 原单独占 49s |
| 段 9 路径规范化改纯字符串运算 | 去掉每条链接 2 次 `cd` |
| 段 12 两次 `find` 合并为一次 | — |
| 查表最终改纯 shell 循环 | 零 fork（中途试过 `printf｜grep｜head｜cut`，反而更慢） |

### 2) 工具自身的执行时间首次纳入预算（`LINT_SECONDS`）

此前 §7 把文档加载量管到字节级，却对"检查自己跑多快"零约束——
那是"机器验"唯一没覆盖到的地方。新增 `LINT_SECONDS=300`，
lint 结束时自报耗时并对照预算。**超时限只告警不 fail**：
机器慢不等于文件错，把性能当 fail 会让人在慢机器上绕过 lint（ADR 0008 已否决）。

### 3) 修 `load-estimate.sh` 的 bash 3.2 兼容问题

- `kws+=("$a")` 数组追加 → 位置参数两趟法。
  数组 `+=` 要 bash 3.1+，且脚本开了 `set -u`，展开空数组在 bash 3.2/4.3 前
  会报 `unbound variable`——也就是"不传关键词"这种该走用法提示的路径会崩。
  **这与 §9.3 声称的"兼容 macOS 自带 bash 3.2"直接矛盾。**
- 顺带修：路径含空格时 `for f in $hits` 会拆错。
- 新增：显式拒收含空白/引号的关键词（否则按词遍历会静默匹配错的东西）。

### 4) 一条命令安装（`install.sh`）

```bash
bash <(curl -fsSL https://gitee.com/idcu/keel-starter/raw/main/install.sh) <项目根>
```

装文件 → 补钩子可执行位 → 装 core.hooksPath → 跑 lint → 打印"还差的三步"。
项目里已有 `keel/` 时走**就地升级**：只补工具链与缺失目录，不覆盖你的
`INDEX.md` / `NOW.md` / `pitfalls/` / `decisions/`（§12.3：升级按字段增量合并）。

**为什么不用 npm**（实测结论，不是判断）：`npm pack` 把 `keel/checks/hooks/`
从 `100755` 打成 `644`，而 lint 第 13 项要求闭环钩子**存在且可执行**——
从 npm 装出来开箱即 fail。git 天然记录权限位（`git ls-files -s` 显示 `100755`）。
本项目零编译零运行时，引入 node 依赖树换可发现性不划算。

### 5) 遵守率：全赛道无人实现的那个指标（ADR 0009）

联网逐个**读源码**核实三个同类项目：

| 项目 | 体量 | 它的"遵守率" | 判定 |
|---|---|---|---|
| `dsh-rule-lens` | 1485 行 JS / 3 提交 / 零测试 | 面板写"遵守率"，但**只有拦截计数、没有分母** | **语义是反的** |
| `aegis` | 41k 行 TS / 989 测试 | adapter 规则第 5 步是 "Self-Review" | **AI 自报 = 不可验** |
| `holaOS` | 48 万行 TS | 全仓 grep → 零实现 | 干脆没做 |

**结论：没有任何项目真正实现了这个指标。**

本项目的口径：**不测 AI 说什么，测文件系统发生了什么**——
`violations.jsonl`（lint 命中 + git diff）+ `load.jsonl`（`load-estimate.sh` 已有）
→ `遵守率 = 1 − 命中轮次 / 总轮次`。**这个数字 AI 一个都改不了。**

依据来自 holaOS 的一份 223 行取证：它的门禁全部正确触发、AI 对目标目录**零编辑**、
然后宣布完成；加重门禁措辞后得到**更精致的形式合规**。

顺带一条反直觉发现，已写进 `pitfalls/_template.md`：
> **在规则里点名失败模式，AI 会精确复现那个失败模式。**

所以「正解」段必须写**具体动作**（"连接走全局单例，在 DAO 构造函数注入"），
不能写"不要在循环里建连接"——后者会让那个组合更显著。

### 6) 新坑三条（都是"该失败时没失败"）

- `xargs -0 CMD "$@"` 会把 `"$@"` 每项当文件名 → awk 读不到文件且**静默产出空结果**
- `NL=$(printf "\n")` 长度 0（命令替换剥掉尾部换行）→ 字符串拆分永不推进 → **死循环**
- `wc -lc` 多文件模式的 `total` 汇总行被当成文件 → 假 fail

### 破坏性与迁移

| 影响 | 迁移动作 |
|---|---|
| lint 行为等价但更快 | 无需动作 |
| 新增 `LINT_SECONDS` | 无需动作；要调上限只改 `budget.env` 一处 |
| `load-estimate.sh` 不再接受含空白/引号的关键词 | 传之前先自行去掉（这类关键词原本也会匹配错） |
| `budget.env` 新增一项 | 无需动作 |
| 新增 `install.sh` | 无需动作；不想用可继续手工 `cp -R` |

### 升级验收（0 fail 才算完成）

```bash
bash keel/checks/keel-lint.sh keel
bash keel/checks/test-lint.sh           # 38/38
python3 keel/checks/mcp/keel-mcp-server.py --self-test   # 8/8
```

> 自测仍为 38 例（性能重构不新增检查项，故用例数不变；
> 新增的 `LINT_SECONDS` 是告警级，不进 fail 检查面）。

## 3.1.1 — 2026-10-01

修 v3.1.0 的一个首次运行缺陷（只在 Keel 自身的两仓布局下暴露，不影响常规用户项目）。

### MCP 服务在"两仓布局"下找不到 keel 目录

`keel-mcp-server.py` 的 `find_keel()` 只**向上**逐级查找，漏了 `keel-starter/keel` 这一层——
于是在项目仓根目录跑 `--self-test` 会报"找不到 keel 目录"。
常规用户项目（`<project>/keel/`）不受影响，问题只在把 keel 目录放在下一级子目录的布局下出现。

修法：候选位置提为常量 `CANDIDATE_SUBDIRS = ("keel", "keel-starter/keel", "")`，
三种布局（`./keel/`、`keel-starter/keel/`、`--keel` 显式指定）均已回归验证。

> 这一条是"新组件必须自己先跑通"的实例：MCP 服务的 8 项自测在 starter 目录里全绿，
> 换个 cwd 就挂——**验证覆盖面本身也是有盲区的**，所以自测要覆盖布置形态，而不只是功能。

### 升级验收

```bash
bash keel/checks/keel-lint.sh keel
bash keel/checks/test-lint.sh                             # 38/38
python3 keel/checks/mcp/keel-mcp-server.py --self-test    # 8/8
```

## 3.1.0 — 2026-10-01

按"评估改进清单"依 ROI 全量推进：两个 P0 修的是**静默失效**，一个 P1 修的是**唯一没有检查形式的硬数字**。
决策记录见 `keel/decisions/0004` – `0007`。

### 1) 孤儿判定改"真实链接图"（P0，行为变更）

旧的"按文件名 grep"两头都会错：正文偶然提及会漏报，文件改名会误报。现在按**解析后的链接目标路径**判定。
**存量仓库升级后可能新报孤儿**——补一行真链接即可（ADR 0004）。回归护栏：新增用例 37。

### 2) 闭环钩子"验谎"（P0，新增 fail 面）

- lint 新增第 16 项：`checks/hooks/{pre-commit,commit-msg}` 必须存在且可执行（§9.1-16）；
- 新增 `checks/verify-hooks.sh`：额外验 `core.hooksPath` 是否挂对；CI 用 `--allow-unset`；
- `install-hooks.sh` 结尾自动复核一次——"装好了"从此不只是脚本的自述（ADR 0005）。

### 3) 单轮加载预算（P1）

`budget.env` 新增 `BYTES_SESSION=15000`（§7.2 的唯一真源）；新增 `checks/load-estimate.sh`，
把 §8 协议第 4 条从"礼貌请求"变成可执行命令（ADR 0006）。

### 4) keel-lite：裁剪成最小集（P1）

`checks/keel-lite.sh`：默认 dry-run，`--apply` 才删；连带剥离 `INDEX.md` 里对应路由行
（否则留死链），裁完自动跑 lint 复核。针对的是评估里"采用成本 4/10"这块最短的板。

### 5) MCP 只读服务 + 检索增强接入位（P2）

- `checks/mcp/keel-mcp-server.py`：把 INDEX / CONSTITUTION / NOW 暴露成 MCP resource，
  只读、零第三方依赖、自带 8 项 `--self-test`（ADR 0007）；
- `checks/check-mcp-config.sh`：校验已声明的 MCP server 可达，**恒 exit 0**（没装不算缺陷）；
- 规格见设计稿 §4.4 / §9.5。

### 6) 两仓发布编排（P3）

`scripts/release.sh`（在项目仓内）：把"先发布仓、后项目仓"这条硬约束写进脚本，
默认 dry-run，推送前自动跑发布仓 lint + 自测。

### 破坏性与迁移

| 影响 | 迁移动作 |
|---|---|
| 新增第 16 项检查 | 确认 `keel/checks/hooks/{pre-commit,commit-msg}` 存在且可执行（`chmod +x`） |
| 孤儿判定变严 | 跑一次 `keel-lint.sh`，给报出的文件补一行真链接（路由表或域索引） |
| 新增 `BYTES_SESSION` | 无需动作；要调上限只改 `budget.env` 一处 |

### 升级验收（0 fail 才算完成）

```bash
bash keel/checks/keel-lint.sh keel
bash keel/checks/test-lint.sh           # 38/38
```

### 其他

- 自测 36 例 → **38 例**（+「缺闭环钩子本体」、+「正文提及但未链接仍判孤儿」）；
- 修掉 `install-hooks.sh` / `verify-hooks.sh` 传入相对路径时前缀匹配失效的 bug；
- 新坑：`pitfalls/meta/link-syntax-example-becomes-real-link.md`（本轮自己踩的——文档里写链接语法示例会被判死链）。

## 3.0.0 — 2026-09-30

设计稿 v3 落地，**破坏性变更三项**：预算数字、frontmatter 必填字段、triggers 计数机制。
决策记录见 `keel/decisions/0001` – `0003`。

### 1) 预算：行数单约束 → 行数 × 字节 × 单行三约束

迁移：

```bash
# 工具链与预算真源以新版整体覆盖（先 diff 保留你在 rules.md 里的扩展声明）
cp -R <新版 starter>/keel/checks/ keel/checks/
bash keel/checks/keel-lint.sh keel    # 存量文档超限会逐条报出，按 §7.3 拆 / 提 / 沉
```

### 2) 根 `INDEX.md` 新增必填字段

迁移：在 `keel/INDEX.md` frontmatter 补两行：

```yaml
keel-version: 3.0.0
project-state: exploring   # exploring | architecture-locked | building | frozen
```

### 3) triggers 计数改由 commit-msg 钩子（废除"会话结束手工 +1"）

迁移（每个 clone 跑一次）：

```bash
bash keel/checks/install-hooks.sh
```

### 其他变更

- 点火锚点进 lint：AGENTS.md / CLAUDE.md / .cursorrules / .cursor/rules 缺 §4.1 原文即 fail
- 域索引（`*/INDEX.md`）只允许表格行（连注释也不行）；"怎么填"移入同目录 `_template*`
- 7 项"声称强制、实则未实现"的检查落入 `keel-lint.sh`（§9.1-2/6/7/8/9/10/11）
- MVP 并入闭环四件套：锚点 + pre-commit + commit-msg + CI（含 PR 模板）
- frontmatter 按 YAML 解析：行内注释剥离；值里禁止 `#`
- 自测 36 例：28 类 fail + 2 类告警 + 6 类合法基线

### 升级验收（0 fail 才算完成）

```bash
bash keel/checks/keel-lint.sh keel
bash keel/checks/test-lint.sh           # 36/36
```

## 2.1.0 — 首个发布

MVP 模板与五步上手（复制 `keel/` → 装钩子 → 贴 CI 与锚点 → lint 0 fail → 自测 36/36）。