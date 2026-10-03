# CHANGELOG

版本号唯一真源：`keel/INDEX.md` frontmatter 的 `keel-version`。
升级按该字段增量合并，**不允许"一键覆盖"**（设计稿 §12.3）。
本仓是发布仓：改动先在此发布，再更新项目仓里的子模块指针。

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