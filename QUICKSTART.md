# 五分钟接入 Keel

> 目标：5 分钟内让一个已有项目跑起 Keel 的门禁，并知道下一步只改哪几个文件。
> 下面的命令都在 2026-11-02 实测通过（v3.6.1）。

## 1. 装（一条命令）

```bash
# 在项目根目录执行（默认不写锚点，只提示）
bash <(curl -fsSL https://gitee.com/idcu/keel-starter/raw/main/install.sh) . --with-anchor

# 要固定版本（推荐）：--ref v3.6.1
# 已 clone 了模板：bash install.sh <项目根> --with-anchor
```

它做四件事：复制 `keel/`、装钩子（pre-commit + commit-msg）、写点火锚点
（`--with-anchor`）、跑第一次 lint。**锚点是硬要求**：没有它 lint 会判死，
这是设计意图——没点火就不算装好。

## 2. 首次门禁（三条）

```bash
bash keel/checks/keel-doctor.sh        # 体检：闭环 / lint / 预算 / 还差你做什么（只读）
bash keel/checks/keel-lint.sh keel     # 必须 0 fail
bash keel/checks/test-lint.sh          # 必须 43/43（42 用例 + 1 元检查）
```

第二条验的是**你的仓库合规**；第三条验的是**你手上的 lint 本身是否可信**
（改检查项时它才是护栏）。两条都绿，机制层就算就绪。

## 3. 最小自定义（只改这几个）

| 文件 | 改什么 | 为什么必须先改 |
|---|---|---|
| `keel/CONSTITUTION.md` | 项目身份、硬约束、人审关卡；把 `<项目名>`、`<技术栈>` 换成真值 | 它是 AI 每次必读的“红线” |
| `keel/INDEX.md` 路由表 | 把占位行换成你项目的真实入口 | 路由是检索入口；占位是孤儿源 |
| `keel/NOW.md` | 当前焦点 / 下一步 / 阻塞（**每轮都要改**） | 会话续接靠它，不是靠记忆 |
| `keel/checks/rules.md` | 只加你项目特有的扩展检查命令 | 通用判据在内核里，别复制一遍 |

> 小项目先裁剪：`bash keel/checks/keel-lite.sh keel` 看计划，
> 加 `--apply` 执行（会连带剥离 INDEX 路由行，避免死链）。
> 痛点到了再加回来：复制同目录的 `_template*` 改名即可。

## 4. 升级与回滚

```bash
bash keel/checks/keel-upgrade.sh --target . --dry-run   # 先看计划（不动文件）
bash keel/checks/keel-upgrade.sh --target . --to v3.6.1 # 升级：前后各跑一次门禁
bash keel/checks/keel-upgrade.sh --target . --rollback  # 回到最近一次升级前
```

- 分类真源是 `keel/checks/manifest.tsv`：内核工具链按版本覆盖；
  `rules.md`/`CONSTITUTION.md`/`decisions`/`pitfalls`/`NOW`/`INDEX` 路由**一律不动**；
  新增结构文件只在父目录已存在时补齐。
- 升级后门禁任一失败会**自动整目录回滚**（备份在 `.keel-backup/`，保留最近 3 份）。
- 已是目标版本会明说「无需升级」，重复执行不产生改动。
- **≤3.5.0 的老仓库**：还没有升级引擎，重跑一次新版 `install.sh` 就是引导路径。

## 5. 常见失败怎么查

| 症状 | 先查 | 修法 |
|---|---|---|
| `❌ 点火锚点缺失` | `AGENTS.md` / `CLAUDE.md` / `.cursor/rules/` | 贴回 §4.1 那一句，或重跑 `install.sh --with-anchor` |
| `❌ 闭环钩子` | `bash keel/checks/verify-hooks.sh .` | `bash keel/checks/install-hooks.sh`（`core.hooksPath` 是本地设置，不进版本库） |
| `❌ 超预算` | `bash keel/checks/load-estimate.sh <关键词>` | 先换更准的关键词；确实词准仍超 → 按拆/提/沉处理 |
| `⚠️ 陈旧` | 文件 frontmatter 的 `last-verified` | 复核后改日期；ADR/坑库有豁免，别为消警告而刷日期 |
| 自测失败 | `bash keel/checks/test-lint.sh --only <编号>` | 先定位是哪条判据，再改 lint 与 §9.3 文档（同一个动作） |
| 中文/编码异常 | `locale`、`bash --version` | bash 3.2 下变量后紧跟中文必须写 `${var}`（见 CONSTITUTION rule 7） |

## 6. 装好后的验收

- [ ] `keel-lint.sh keel` 0 fail
- [ ] `test-lint.sh` 43/43
- [ ] `keel-doctor.sh` 第 5 节“还差你亲手”的三项已清零
- [ ] 改一个 `keel/*.md` 后 `git commit` 会被 pre-commit 拦住（证明钩子真的挂上了）

下一步不是继续配工具，而是**用几天**：看 AI 在哪类事上仍反复出错，
再把那一条补进 `CONSTITUTION` / `pitfalls`。Keel 的价值来自你补的那几条，
不是来自骨架本身。
