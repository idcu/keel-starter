# CHANGELOG

版本号唯一真源：`keel/INDEX.md` frontmatter 的 `keel-version`。
升级按该字段增量合并，**不允许"一键覆盖"**（设计稿 §12.3）。
本仓是发布仓：改动先在此发布，再更新项目仓里的子模块指针。

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