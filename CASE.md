# 案例：一个 8000+ 用例项目怎么用 Keel

> 这是一份**实测记录**，不是宣传稿。所有数字都来自 2026-11-02 在本机的真实执行，
> 没跑过的数字一律不写；版本标注比"好看"更重要。

## 1. 对象与接入前状态

lytjs 是一个 TypeScript 前端框架项目，测试规模 **8436 个用例 / 385 个文件**。
它把 Keel 以 **vendored** 方式放在自己的仓库里（`keel/` 目录整体提交，不是 submodule），
因此"升级 Keel"就是一次普通的代码变更，走它自己的 review 与门禁。

升级前（2026-11-02 上午）的状态：

| 项 | 值 |
|---|---|
| Keel 版本 | **3.4.11** |
| `keel-lint.sh keel` | 0 fail，约 2s（55 篇热区文档） |
| 已知隐患 | 段 3 有一个 `LC_ALL=C` 泄漏赋值、段 4 用了 locale 依赖的 `*[A-Z]*` glob。当前能过属于"歪打正着"，换台机器（`zh_CN.UTF-8`）可能误报 |

> 说明：团队接入 Keel 之前的状态没有留下可核实的数据，本文不写。
> 下面所有对比都以**可复现的门禁输出**为准。

## 2. 升级 3.4.11 → 3.5.0：修掉"脆弱正确"

第一次升级（当天上午，提交 `dab27d73`）只动了工具链：`keel-lint.sh`、钩子、
`test-lint.py` 与检索工具，**没碰项目自己的** `rules.md` / `CONSTITUTION.md` /
`decisions/` / `pitfalls/` / `NOW.md`。

| 项 | 升级前（3.4.11） | 升级后（3.5.0） |
|---|---|---|
| `keel-lint.sh keel` | 0 fail，2s | 0 fail，1.82s（locale 加固后仍稳） |
| `test-lint.sh` | 43/43 | 43/43 + LOCALE/PROSE 通过，13.8s |
| 业务全量测试 | 8436/8436，323.6s | 8436/8436，317.23s |
| fast 门禁 | 11/11，11.6s | 12/12，5.4s |
| 覆盖率（statements） | 66.50%（旧数据，未重跑） | **87.66%**（clover.xml，同日实测） |

结论：**locale 修复没有暴露此前被掩盖的新问题**——两个 locale 下段 4 都不误报。

## 3. 升级 3.5.0 → 3.7.0：第一次用 `upgrade` 命令

这次是真正的"外部采用方第一次用升级引擎"。先按直觉执行：

```bash
bash keel/checks/keel-upgrade.sh --target . --to v3.7.0
# bash: keel/checks/keel-upgrade.sh: No such file or directory  (exit 127)
```

3.5.0 的仓库里**还没有升级引擎**（它是 3.6.0 才引入的）。正确路径是重跑安装脚本，
它会检测到已有 `keel/` 并委派升级：

```bash
bash <(curl -fsSL https://gitee.com/idcu/keel-starter/raw/v3.7.0/install.sh) . --ref v3.7.0
```

| 项 | 结果 |
|---|---|
| 退出码 | **0** |
| 全流程耗时 | **49.5s**（含在线拉取模板 + 升级 + 前后各跑一次门禁） |
| 改动 | 内核覆盖 21 · 新增 5 · **保留 47** |
| 你的自定义文件 | `rules.md` / `CONSTITUTION.md` / `decisions/` / `pitfalls/` / `NOW.md` 哈希全等，一个字节没动 |
| 幂等 | 再跑一次：`✅ 已是 v3.7.0，无需升级`，exit 0 |
| 备份 | `.keel-backup/`，一条命令回滚 |

升级前后门禁（在同一副本内实跑）：

| 门禁 | 3.5.0 工具 | 3.7.0 工具 |
|---|---|---|
| `keel-lint.sh keel` | 0 fail（2.77s） | 0 fail（3.02s） |
| `test-lint.sh` | 43/43（19.5s） | 43/43（20.3s） |
| 固定加载预算 | 4861B ≤ 15000B | 4861B ≤ 15000B |

**没被门禁拦住，也没有升级后返工。** 唯一的人工介入就是上面那条 127——文档缺口，不是脚本问题。

## 4. 踩到的三个坑（与修法）

| 坑 | 症状 | 修法 |
|---|---|---|
| 没有升级引擎 | `No such file or directory`（exit 127） | 重跑 `install.sh --ref v3.7.0`；QUICKSTART 已在 §4 开头写明先 `ls` 一次 |
| locale 脆弱正确 | 段 3 泄漏 `LC_ALL=C`、段 4 用 `*[A-Z]*` glob，换机器可能误报 | 升到 3.5.0+：`LC_ALL` 改成命令前缀，glob 改字母表展开 |
| 文件权限漂移 | 升级时 `test-lint.py` 从 755 变 644 | 清单（`manifest.tsv`）记录权限，升级按清单校准；3.7.0 起发布侧 `--check-manifest` 提前拦漂移 |

## 5. 可复制的命令（本次全部真跑过）

```bash
# 看当前版本
grep '^keel-version:' keel/INDEX.md

# 有引擎之后：升级 / 回滚
bash keel/checks/keel-upgrade.sh --target . --to v3.7.0
bash keel/checks/keel-upgrade.sh --target . --rollback

# 每次改完 keel/ 都跑（两个都在秒级~十秒级）
bash keel/checks/keel-lint.sh keel
bash keel/checks/test-lint.sh

# 发布方/CI：清单与实际文件的哈希、权限、版本是否一致
bash keel/checks/keel-upgrade.sh --check-manifest keel
```

## 6. 边界（没验证的不写）

- **单样本**：目前只有 lytjs 一个真实采用方，结论不能外推到所有项目；
- **业务侧数字带版本**：8436 用例、87.66% 覆盖率是 3.5.0 当天实测；3.7.0 升级只改 `keel/`，
  **没有重跑业务套件**，因此不宣称"3.7.0 下仍 8436 全绿"；
- **未覆盖**：升级中途强制中断的断点恢复（`--rollback` 只覆盖"门禁失败"这条路径）；
- 想自己复现：从 [TRY-KEEL.md](TRY-KEEL.md) 开始，三分钟看到你自己项目的真实数字。
