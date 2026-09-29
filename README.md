# keel-starter

Keel 的模板仓库。它要解决的问题只有一句：

> **AI 每次开新会话，都像一个手速极快、但每天早上失忆的实习生。**
> Keel 给这个实习生配齐：入职手册 + 工作台 + 错题本 + 交接本 + 质检台。

做法不是"把文档写全"，而是把成本从**总量**挪到**单次**：
内容可以长到 1GB，但每次会话的固定加载量恒定在 **≤5k token**（约 1.9k 是必读部分）。

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

# 5. 自测：必须 36/36
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

## 三个命令

```bash
bash keel/checks/keel-lint.sh keel        # 一致性校验：0 fail 才放行（pre-commit 与 CI 都跑它）
bash keel/checks/test-lint.sh             # lint 自测：36 例故障注入 + 脚本与文档一致性
bash keel/checks/install-hooks.sh         # 装钩子（每人 clone 后跑一次）
```

## 闭环怎么被守住

会话结束时该做的事（写回 `NOW.md`、登记新坑、跑 lint）**不靠自觉**，靠四处钩子：

| ① 锚点 | ② pre-commit | ③ commit-msg | ④ CI |
|---|---|---|---|
| 每次任务开始先读 INDEX + NOW | `keel/` 下 md 变更即跑 lint，0 fail 才放行 | message 里写 `pitfall: <文件名>` 自动给 `triggers` +1 | lint 0 fail + 自测 36/36 |

**缺一处，闭环就退化成自觉。**

## 约定（改之前先看这几条）

- **预算数字的唯一真源是 `keel/checks/budget.env`**，改预算只改它；`keel-lint.sh` 里的是兜底默认值
- **预算 = 行数 × 字节 × 单行**三约束（行数不是 token 的有效代理：同一个"≤30 行"上限下，实测可差 10 倍）
- **钩子本体版本化在 `keel/checks/hooks/`**；`core.hooksPath` 属于本地配置、不进版本历史，
  所以**每个 clone 都要跑一次第 2 步**（CI 是这件事的兜底）
- **域索引（`*/INDEX.md`）只允许表格行**，"怎么填"写在同目录的 `_template*` 里——索引负责定位，模板负责教怎么填
- **改了 `keel/checks/keel-lint.sh` 必须同时改 `test-lint.py`**，否则自测红（那条用例专门防这个）
- 自测需要 python3；**`keel-lint.sh` 本体只依赖 bash 3.2+ / awk / sed / find**（外加可选的 `tsort`、`git`）
