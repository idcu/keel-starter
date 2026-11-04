---
scope: meta
status: active
last-verified: 2026-11-03
keywords: [钩子, 闭环, 验谎, lint]
type: decision
created: 2026-10-01
superseded-by:
---

# 0005 闭环钩子必须"验谎"：lint 第 16 项 + verify-hooks.sh

## 背景

§10.4 立了铁律：①②③④（锚点 / pre-commit / commit-msg / CI）缺一，强制闭环不成立。
但 v3 只把①（锚点）送进了 lint，②③ 完全没人管——于是它们有两种**静默失效**方式：

1. 钩子本体被误删、或 checkout 时丢了可执行位 → 钩子不再触发，没人知道；
2. 本体在，但 `core.hooksPath` 没挂上（**每个 clone 都要跑一次 install-hooks.sh**）→ 同样静默。

第 2 种最危险：`install-hooks.sh` 打印的"✅ 已安装"只是**脚本的自述**，不是可复核的事实。

## 决定

拆成两层，各自放在能验的地方：

- **lint 第 16 项（§9.1-16）**：`checks/hooks/{pre-commit,commit-msg}` 必须存在且可执行。进 CI，
  防的是"本体被误删"；
- **`checks/verify-hooks.sh`**：额外验 `core.hooksPath` 是否指向 `<keel>/checks/hooks`。默认语义下
  "未挂载"判 ❌；CI 用 `--allow-unset`（新 clone 天然没装）。`install-hooks.sh` 结尾**自动复核一次**。

## 被否掉的选项

| 选项 | 为什么没选 |
|---|---|
| 只在 install-hooks.sh 里 echo 一句"已安装" | 自述不等于事实；上一个会话/另一个人可能根本没跑 |
| 让 CI 也判 `core.hooksPath` | CI 是全新 clone，必然未挂载，判死等于每次都红 |
| 把钩子内容复制进 `.git/hooks/` | 不可评审、不随分支走，与 §7.4 的选择相矛盾 |
| 用 pre-commit 框架（`.pre-commit-config.yaml`） | 多一层外部依赖，违反内核零依赖 |

## 后果

- 好处：闭环第一次有了"装没装"的客观判据；安装脚本自己也被同一个尺子复核。
- 代价：**存量仓库升级后会新增一个 fail 面**——若曾把 `checks/hooks/` 删掉或没保留可执行位，lint 会红；
  修复是补回本体并 `chmod +x`（Windows 下建议 `git update-index --chmod=+x`）。
- 顺带修掉一个真 bug：`install-hooks.sh` / `verify-hooks.sh` 传入相对路径时前缀匹配会失效，已统一归一化。

## 修订 · v3.11.0：验证清单也是「验谎」的对象

同一种失效换了个位置：发布说明可以自述无条件通过，而故障自测 / 跨版本矩阵根本没跑。

- `checks/verify/verify.py` 跑完整套件并写 `verify-report.json`：套件名、`PASS/FAIL/SKIP`、
  跳过原因、用例数、耗时、环境（平台 / locale / 容器镜像 / 引擎版本）、覆盖的矩阵格；
  有跳过时汇总输出「未全部覆盖」，不输出无条件通过。
- `checks/verify/check-verify-report.py` 是判据：套件标 `PASS` 却 `skipped>0` = **伪装 PASS**；
  含 SKIP/FAIL 时发行说明出现无条件通过即失败；含 SKIP 必须写「X 通过 / Y 跳过（未验证）」。
  `--selftest` 用 8 个构造样例（含「含 SKIP + 无条件通过」「跳过数写成 0」）证明判据会红。
- `scripts/release.sh --apply` 推送前跑清单，并用判据校验 `CHANGELOG.md` **当前版本小节**；
  不一致即中止。历史小节不参与，避免旧文案让本轮变红。
- 采用方复现：`bash keel/checks/verify/verify.sh --out verify-report.json`。
- 故障自测环境探测分五态，无 Docker 默认跳过并计入未验证（`exit 0`）；
  `KEEL_FAULTS_REQUIRE_DOCKER=1` 才变红。理由与本文原文一致：自述不等于事实，
  但「环境缺能力」也不该伪装成代码失败。
- 决策落在既有条目而非新增：decisions/ 的 20 文件上限与索引 181B 余额都容不下
  一条独立 ADR；本条是 0005「验谎」语义的直接延伸。

## 修订 · v3.12.0：绿不能盖住跳过

清单存在了，但若 CI 页面只显示绿，跳过仍等于没发生。

- CI 的 `test-faults` 与跨版本矩阵两步把 `SKIP` 行**连同原因**写进
  `GITHUB_STEP_SUMMARY`（矩阵用 `grep -A3 "^\[SKIP\]"` 保留原因行）；
  无该变量时写 `/dev/null`，本地复跑不产生副作用。
- 矩阵步骤的 `checkout` 必须 `fetch-depth: 0`：浅 clone 取不到历史 tag 会把整格变
  SKIP，而摘要若不显示原因，页面上就只剩绿色——**缺能力被读成通过**。
- 判据边界：CI 摘要只是"可见"，不改变退出码；跳过是否放行仍由
  `KEEL_FAULTS_REQUIRE_DOCKER=1` / 矩阵格自身决定。可见性 ≠ 门禁强度。
- v3.14.0：清单自身也要绑定到代码——provenance（commit / dirty / 4 文件 sha256）
  与 `--repo` 校验见 ADR 0002 的对应修订；本条不重复。

