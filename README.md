# keel-starter

[![keel-starter CI](https://github.com/idcu/keel-starter/actions/workflows/keel.yml/badge.svg)](https://github.com/idcu/keel-starter/actions/workflows/keel.yml)
[![keel CI](https://github.com/idcu/keel/actions/workflows/keel.yml/badge.svg)](https://github.com/idcu/keel/actions/workflows/keel.yml)
[![keel-version](https://img.shields.io/badge/keel--version-3.4.10-4B3FE3)](https://github.com/idcu/keel-starter/blob/main/keel/INDEX.md)

> 徽章指向 GitHub 镜像（Gitee 无标准徽章端点）。**发布仓**徽章是产品健康度，**项目仓**徽章守的是
> "设计稿与脚本不许漂移"这条不变量——两者的关系与镜像同步的有序性见设计稿 §12.3。

Keel 的模板仓库。它要解决的问题只有一句：

> **AI 每次开新会话，都像一个手速极快、但每天早上失忆的实习生。**
> Keel 给这个实习生配齐：入职手册 + 工作台 + 错题本 + 交接本 + 质检台。

做法不是"把文档写全"，而是把成本从**总量**挪到**单次**：
内容可以长到 1GB，但每次会话的固定加载量恒定在 **≤5k token**（约 1.9k 是必读部分）。

> **tag 说明**：版本号有两处真源——`keel/INDEX.md` 的 `keel-version` 与本仓的
> `vX.Y.Z` tag。两者一致（CI 与发布流程保证），`--ref` 认的是 **tag**。
> 没有 tag 的版本等于不存在：声明了但拉不到。

**第一次来？先看 [TRY-KEEL.md](TRY-KEEL.md)** —— 3 分钟装完并看到你自己项目的真实数字，
含doctor 五项结果怎么读、常见报错对照表。

## 一条命令装上

```bash
bash <(curl -fsSL https://gitee.com/idcu/keel-starter/raw/main/install.sh) <你的项目根>
```

装完还差三步（**缺任一步，这套系统等于不存在**）：贴锚点、填自己的内容、小项目先裁剪。
脚本会把三步打给你。

**嫌第 1 步麻烦**？加 `--with-anchor`，我直接把锚点写进 `AGENTS.md`
（默认不写——那是你的文件。已存在锚点时，无论加不加开关都不会动它）：

```bash
bash <(curl -fsSL https://gitee.com/idcu/keel-starter/raw/main/install.sh) <项目根> --with-anchor
```

**装完先跑这个**（3 分钟看到你这套 Keel 现在什么样，只读不改）：

```bash
bash keel/checks/keel-doctor.sh
```

它逐项报 5 件事：闭环门禁（锚点 + 钩子本体 + 挂载点）、lint 结果、单轮加载预算、
判据自检怎么跑、还有哪些需要你亲手填。**不修复、不改文件**——诊断与修复分开。

已clone 下来了就直接 `bash install.sh <项目根>`；
**要固定版本**加 `--ref`（`--ref v3.4.6` 或 `--ref=v3.4.6` 都行）——
指定了版本拉不到就会**报错并列出可用版本**，不会偷偷给你装 `main`。
项目里已有 `keel/` 时它走**就地升级**——只补工具链与缺失目录，不覆盖你的
`INDEX.md` / `NOW.md` / `pitfalls/` / `decisions/`（设计稿 §12.3：升级按字段增量合并）。

**为什么不用 npm**（v3.2 实测）：`npm pack` 把 `keel/checks/hooks/` 从 `100755`
打成 `644`，而 lint 第 13 项要求闭环钩子**存在且可执行**——从 npm 装出来开箱即 fail。
git 天然记录权限位（`git ls-files -s` 显示 `100755`），clone 下来就是对的。
本项目零编译零运行时，引入 node 依赖树换可发现性不划算。

## 五步上手（第 0 天）

```bash
# 1. 把 keel/ 复制进你的项目根
cp -R keel /path/to/your-project/keel

# 2. 装钩子（pre-commit + commit-msg）
cd /path/to/your-project && bash keel/checks/install-hooks.sh

# 3. 贴 CI 片段，并把 AGENTS.md 里那一句放进你的工具规则
cp .github/workflows/keel.yml /path/to/your-project/.github/workflows/
#    锚点那一句 → 你的 CLAUDE.md / .cursor/rules/keel.mdc / 系统提示

# 4. 内核校验：必须 0 fail
bash keel/checks/keel-lint.sh keel

# 5. 自测：必须 42/42
bash keel/checks/test-lint.sh
```

两个容易忽略的点：

- **第 3 步那句锚点是整套系统的开关。** 检索协议写在 `INDEX.md` 里面，但 AI 不会凭空知道去读它——
  协议在门内，钥匙必须在门外。不进工具规则，Keel 等于不存在。
- **第 5 步验的不是你的仓库**，而是**你手上的 lint 到底能不能判死它声称能判死的问题**。
  将来你改检查项时，它是唯一的护栏。缺 python3 时它会跳过并返回 2（不误报失败）。

## 目录

| 路径 | 是什么 | 什么时候需要 |
|---|---|---|
| `keel/INDEX.md` | 唯一必读入口：检索协议 + 路由表 + 项目状态 | 一定有 |
| `keel/CONSTITUTION.md` | 红线 + 人审关卡 + 项目状态机 | 一定有 |
| `keel/NOW.md` | 当前焦点、下一步、阻塞、交接 | 每次会话都要改 |
| `keel/pitfalls/` | 坑库（症状 / 根因 / 正解） | 踩坑就加 |
| `keel/checks/` | lint + 预算真源 + 钩子 + 自测 + 扩展检查位 | 一定有 |
| `keel/ARCHITECTURE.md` | 模块边界与依赖方向矩阵 | 有人搞错边界时 |
| `keel/contracts/` | API / 类型 / 事件的唯一真源 | 改了接口、调用方漏改时 |
| `keel/GLOSSARY.md` | 术语唯一写法 / 禁止写法 | 同一概念出现第二种写法时 |
| `keel/decisions/` | 决策记录（ADR） | 出现"当初为什么这么定"时 |
| `keel/skills/` | 可复用操作手册 | 同一个操作第二次被口述时 |
| `keel/env/` | 依赖锁 / 密钥来源 / 配额 / mock | 有第二个环境时 |

后六项是**按需层**：不进 MVP，痛点到了再加（规格见设计稿 §5.7）。
所有空目录里都有 `_template*` 或 `_template.schema.json`，复制改名即可。

## 命令

```bash
# 日常三个
bash keel/checks/keel-lint.sh keel        # 一致性校验：0 fail 才放行（pre-commit 与 CI 都跑它）
bash keel/checks/test-lint.sh             # lint 自测：41 用例 + 元检查 + 脚本与文档一致性
bash keel/checks/test-lint.sh --only 6,39-41   # 只跑指定用例（改判据时用，秒级；发版前仍须全量）
bash keel/checks/install-hooks.sh         # 装钩子（每人 clone 后跑一次，装完自动复核）

# 按需
bash keel/checks/verify-hooks.sh          # 钩子"验谎"：本体可执行 + 挂载点正确（CI 加 --allow-unset）
bash keel/checks/load-estimate.sh 关键词   # 本轮要读多少字节？超预算即非零退出（§8 协议第 4 条）
bash keel/checks/keel-lite.sh keel        # 裁掉按需层成最小集（默认 dry-run，--apply 才动手）
bash keel/checks/compliance.sh report     # 遵守率 + 存量合规率（§11.2 / ADR 0009 / ADR 0011）
bash keel/checks/compliance.sh backfill --max 10   # 回填历史提交（出"存量合规率"；先加 --dry 看会跑几个）
python3 keel/checks/mcp/keel-mcp-server.py --self-test   # MCP 只读服务自测（8 项）
bash keel/checks/check-mcp-config.sh      # 已声明的 MCP server 是否可达（未声明即正常）
```

## 小项目：先裁成最小集

全量骨架带 6 个"按需层"（`contracts/` `env/` `skills/` `decisions/` `ARCHITECTURE.md` `GLOSSARY.md`）。
用不上就先裁掉——`keel-lite.sh` 会**连带剥离 `INDEX.md` 里的对应路由行**，否则删了目录就留死链：

```bash
bash keel/checks/keel-lite.sh keel           # 先看计划（dry-run，不动文件）
bash keel/checks/keel-lite.sh keel --apply   # 确认后执行；裁完自动跑 lint 复核
```

痛点到了再加回来：starter 一直带着骨架，复制 `_template*` 改名即可（规格见设计稿 §5.7）。

## 接了 MCP 的话

`keel/checks/mcp/keel-mcp-server.py` 把 INDEX / CONSTITUTION / NOW 暴露成**只读** MCP resource——
让"必读"变成协议动作，而不是提示词里的礼貌请求（设计稿 §4.2 / §4.4）：

```json
{"mcpServers": {"keel": {"command": "python3",
  "args": ["<绝对路径>/keel/checks/mcp/keel-mcp-server.py"]}}}
```

想补齐 `grep` 的语义召回（Serena 等），也走同一个接入位，见设计稿 §9.5。

## 闭环怎么被守住

会话结束时该做的事（写回 `NOW.md`、登记新坑、跑 lint）**不靠自觉**，靠四处钩子：

| ① 锚点 | ② pre-commit | ③ commit-msg | ④ CI |
|---|---|---|---|
| 每次任务开始先读 INDEX + NOW | `keel/` 下 md 变更即跑 lint，0 fail 才放行 | message 里写 `pitfall: <文件名>` 自动给 `triggers` +1 | lint 0 fail + 自测 42/42 |

**缺一处，闭环就退化成自觉。** 所以②③也在检查面内：lint 第 16 项管"钩子本体在不在且可执行"（防误删），
`verify-hooks.sh` 管"本地到底装没装"（`core.hooksPath`）——两者都失效才是真正没人知道的静默故障。

## 约定（改之前先看这几条）

- **预算数字的唯一真源是 `keel/checks/budget.env`**，改预算只改它；`keel-lint.sh` 里的是兜底默认值
- **预算 = 行数 × 字节 × 单行**三约束（行数不是 token 的有效代理：同一个"≤30 行"上限下，实测可差 10 倍）
- **钩子本体版本化在 `keel/checks/hooks/`**；`core.hooksPath` 属于本地配置、不进版本历史，
  所以**每个 clone 都要跑一次第 2 步**（CI 是这件事的兜底）
- **域索引（`*/INDEX.md`）只允许表格行**，"怎么填"写在同目录的 `_template*` 里——索引负责定位，模板负责教怎么填
- **改了 `keel/checks/keel-lint.sh` 必须同时改 `test-lint.py`**，否则自测红（那条用例专门防这个）
- **孤儿 = 没有被任何热区文档用链接指向**。正文里提到文件名不算引用——写文档时别把链接字面量当例子
  （会当场被判死链，见 `pitfalls/meta/link-syntax-example-becomes-real-link.md`）
- 自测需要 python3；**`keel-lint.sh` 本体只依赖 bash 3.2+ / awk / sed / find**（外加可选的 `tsort`、`git`）。
  MCP 服务同样只依赖 python3 标准库，且**不进内核**——`keel-lint.sh` 不引用它
