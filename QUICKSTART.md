# 五分钟接入 Keel

> 目标：5 分钟内让一个已有项目跑起 Keel 的门禁，并知道下一步只改哪几个文件。
> 下面的命令都在 2026-11-02 实测通过（v3.7.0）。

## 1. 装（一条命令）

```bash
# 在项目根目录执行（默认不写锚点，只提示）
bash <(curl -fsSL https://gitee.com/idcu/keel-starter/raw/main/install.sh) . --with-anchor

# 要固定版本（推荐）：--ref v3.9.1
# 已 clone 了模板：bash install.sh <项目根> --with-anchor
```

它做四件事：复制 `keel/`、装钩子（pre-commit + commit-msg）、写点火锚点
（`--with-anchor`）、跑第一次 lint。**锚点是硬要求**：没有它 lint 会判死，
这是设计意图——没点火就不算装好。

## 2. 首次门禁（三条）

```bash
bash keel/checks/keel-doctor.sh        # 体检：闭环 / lint / 预算 / 还差你做什么（只读）
bash keel/checks/keel-lint.sh keel     # 必须 0 fail
bash keel/checks/test-lint.sh          # 必须 50/50（48 用例 + 2 元检查）
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

**先确认你手上有没有升级引擎**：`ls keel/checks/keel-upgrade.sh`。
没有（≤3.5.0 的仓库就是这样）就重跑一次 `install.sh`——它会把新引擎拉起来并**直接升级**，
不需要先手工拷脚本：

```bash
bash <(curl -fsSL https://gitee.com/idcu/keel-starter/raw/main/install.sh) . --ref v3.12.0
```

有了引擎之后，日常升级与回滚：

```bash
bash keel/checks/keel-upgrade.sh --target . --dry-run    # 先看计划（不动文件）
bash keel/checks/keel-upgrade.sh --target . --to v3.12.0 # 升级：前后各跑一次门禁
bash keel/checks/keel-upgrade.sh --target . --rollback   # 回到最近一次升级前
```

- **两阶段引导（v3.10.0）**：从 v3.6–v3.9.x 升级时，旧引擎只负责取模板与校验，
  实际升级由**目标版本的新引擎**以子进程执行（交接状态在 `.keel-bootstrap.pending`）。
  这样做是因为"升级判据属于目标版本"——旧引擎执行到底，新判据永远轮不到旧仓库。
  模板校验不过（版本 / manifest / sha256 / 权限）会在交接前 `exit 2`，目标一个字节都不动。
  旧引擎的裸 `cp` 会截断正在执行的脚本，所以**升级请走 `install.sh` 或新引擎**；
  直接从 ≤3.9.x 原地跑旧引擎在部分版本上会自伤（矩阵已隔离并记录该缺陷）。
- 分类真源是 `keel/checks/manifest.tsv`：内核工具链按版本覆盖；
  `rules.md`/`CONSTITUTION.md`/`decisions`/`pitfalls`/`NOW`/`INDEX` 路由**一律不动**；
  新增结构文件只在父目录已存在时补齐。
- 升级后门禁任一失败会**自动整目录回滚**（备份在 `.keel-backup/`，保留最近 3 份）。
- 已是目标版本会明说「无需升级」，重复执行不产生改动。
- 升级**中途被强杀**（Ctrl-C / 断网 / 磁盘满）：重跑会提示存在未完成升级并 `exit 5`；
  `--resume` 只处理剩余文件（先校验已写文件 sha256），`--rollback` 整目录还原字节与权限。
  旧引擎（尤其 ≤3.9.x）盘上没有 `--resume`：**重跑 `install.sh`** 即可，它会检测
  `.keel-upgrade.pending` 并让目标版本引擎带着 `--resume` 接手（v3.11.0 修复）。

## 5. 常见失败怎么查

| 症状 | 先查 | 修法 |
|---|---|---|
| `❌ 点火锚点缺失` | `AGENTS.md` / `CLAUDE.md` / `.cursor/rules/` | 贴回 §4.1 那一句，或重跑 `install.sh --with-anchor` |
| `❌ 闭环钩子` | `bash keel/checks/verify-hooks.sh .` | `bash keel/checks/install-hooks.sh`（`core.hooksPath` 是本地设置，不进版本库） |
| `❌ 超预算` | `bash keel/checks/load-estimate.sh <关键词>` | 先换更准的关键词；确实词准仍超 → 按拆/提/沉处理 |
| `⚠️ 陈旧` | 文件 frontmatter 的 `last-verified` | 复核后改日期；ADR/坑库有豁免，别为消警告而刷日期 |
| `bash: keel/checks/keel-upgrade.sh: No such file` | `ls keel/checks/keel-upgrade.sh` | 你停在 ≤3.5.0，还没有升级引擎；重跑 `install.sh --ref v3.10.0`（见 §4 开头） |
| 自测失败 | `bash keel/checks/test-lint.sh --only <编号>` | 先定位是哪条判据，再改 lint 与 §9.3 文档（同一个动作） |
| 中文/编码异常 | `locale`、`bash --version` | bash 3.2 下变量后紧跟中文必须写 `${var}`（见 CONSTITUTION rule 7） |

## 6. 装好后的验收

- [ ] `keel-lint.sh keel` 0 fail
- [ ] `test-lint.sh` 50/50
- [ ] `keel-doctor.sh` 第 5 节“还差你亲手”的三项已清零
- [ ] 改一个 `keel/*.md` 后 `git commit` 会被 pre-commit 拦住（证明钩子真的挂上了）

**验证覆盖到哪，要能自己复现**：

```bash
bash keel/checks/verify/verify.sh --out verify-report.json   # 跑完整清单
python3 keel/checks/verify/check-verify-report.py --report verify-report.json --summary
```

- `test-faults.py` 需要 Docker linux 容器。**没有 Docker 时它不是 PASS**：输出
  `SKIP(no-binary / no-daemon)` 并在汇总单列「0 通过 / 0 失败 / N 跳过（未验证）」，
  默认 `exit 0`（CI 不因环境缺能力变红）；
  门禁若要求真跑故障注入，设 `KEEL_FAULTS_REQUIRE_DOCKER=1` → `exit 1`。
- 清单里只要有 SKIP，发行说明就**不得**出现无条件通过表述，必须写
  「X 通过 / Y 跳过（未验证）」；`check-verify-report.py` 会在发布前判死这类含混表述。
- 矩阵 `KEEL_MATRIX_VERSIONS` 可配置起点；设 `KEEL_MATRIX_OFFLINE=1` 时取不到快照的格
  记 SKIP（不是 PASS）。`KEEL_MATRIX_JOBS=4` 可并行各格，断言一条不减。

下一步不是继续配工具，而是**用几天**：看 AI 在哪类事上仍反复出错，
再把那一条补进 `CONSTITUTION` / `pitfalls`。Keel 的价值来自你补的那几条，
不是来自骨架本身。
