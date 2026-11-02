#!/usr/bin/env python3
"""keel-upgrade 自测套件（DESIGN.md §12.3 / ADR 0020）

用法：
    bash   keel/checks/test-upgrade.sh [-v] [--keep]
    python3 keel/checks/test-upgrade.py [-v] [--keep]

做什么：
    用**离线临时仓库**验证升级引擎的 5 条硬承诺：
      ① 正常升级：内核覆盖、新增补齐、自定义原样、版本行被合并
      ② 跨多个版本升级（3.3.0 → 当前版本）
      ③ 升级前后各跑门禁（lint / test-lint / 预算固定成本）
      ④ 升级后门禁失败 → 自动回滚到升级前
      ⑤ 幂等：重复执行 / 已是目标版本 → 明确「无需升级」，不产生额外改动
    另加三条防腐烂断言：manifest 与实际文件一致（含权限位）、改 kernel 不改清单必须判死、
    dry-run 零改动。

为什么需要它：升级工具是**采用方唯一会跑的破坏性操作**。它错了不是"提示难看"，
而是把人家的仓库改坏。lint 自测守的是判据，这里守的是"改文件"本身。

依赖：python3（仅测试用）。升级引擎本体只依赖 bash 3.2+ / awk / sed / cp / sha256。
"""

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
KEEL = os.path.dirname(HERE)                     # 待分发的 keel/ 目录（本套件所在的模板）
UPGRADE = os.path.join(HERE, "keel-upgrade.sh")
BASH = shutil.which("bash") or "bash"

ANCHOR = "任何任务开始前，先读 keel/INDEX.md 与其中指向的 NOW.md，并遵守 INDEX.md 里的检索协议。"

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


def read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)


def _shipable(keel_dir):
    """这个 keel/ 能不能单独分发？规格仓里的实例会引用仓外文件（../DESIGN.md 等），
    fixture 里没有它们，升级前门禁会因死链失败——那不是引擎的错。"""
    try:
        return "../" not in read(os.path.join(keel_dir, "INDEX.md"))
    except OSError:
        return False


# 规格仓（本项目）里的 keel/ 是实例，不是可分发模板：自动改用同级发布仓的模板，
# 否则 8 个用例会全部卡在"fixture 缺 ../DESIGN.md"这一步（实测踩过）。
if not _shipable(KEEL):
    _sibling = os.path.normpath(os.path.join(KEEL, "..", "keel-starter", "keel"))
    if _shipable(_sibling):
        print("· 本 keel/ 是规格仓实例（引用仓外文件），改用发布模板: %s" % _sibling)
        KEEL = _sibling
        UPGRADE = os.path.join(_sibling, "checks", "keel-upgrade.sh")


def version_of(keel_dir):
    for line in read(os.path.join(keel_dir, "INDEX.md")).splitlines():
        if line.startswith("keel-version:"):
            return line.split(":", 1)[1].strip()
    return ""


def run_upgrade(args, cwd):
    p = subprocess.run([BASH, UPGRADE] + args, cwd=cwd,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return p.returncode, p.stdout.decode("utf-8", "replace")


def make_target(root, version, drop_retrieval=True):
    """造一个"旧版本"采用方仓库：模板副本 + 降版本 + 旧内核标记。"""
    tgt = os.path.join(root, "proj")
    os.makedirs(tgt, exist_ok=True)
    shutil.copytree(KEEL, os.path.join(tgt, "keel"))
    write(os.path.join(tgt, "AGENTS.md"), "# test\n" + ANCHOR + "\n")
    # 降级 keel-version
    idx = os.path.join(tgt, "keel/INDEX.md")
    text = read(idx)
    text = "\n".join(
        ("keel-version: " + version) if l.startswith("keel-version:") else l
        for l in text.splitlines()) + "\n"
    write(idx, text)
    # 旧版没有的手册文件：retrieval（内核新增）
    if drop_retrieval:
        shutil.rmtree(os.path.join(tgt, "keel/checks/retrieval"), ignore_errors=True)
        mf = os.path.join(tgt, "keel/checks/manifest.tsv")
        lines = [l for l in read(mf).splitlines(True) if "checks/retrieval/" not in l]
        write(mf, "".join(lines))
    # 旧内核内容标记（升级后应被覆盖掉）
    with open(os.path.join(tgt, "keel/checks/keel-lint.sh"), "a", encoding="utf-8") as fh:
        fh.write("\n# OLD-KERNEL-MARK\n")
    # 重算旧 fixture 自己的 manifest（让"本地修改检测"有基线）
    p = subprocess.run([BASH, os.path.join(tgt, "keel/checks/keel-upgrade.sh"),
                        "--regen-manifest", os.path.join(tgt, "keel")],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert p.returncode == 0, p.stdout.decode("utf-8", "replace")
    return tgt


def template_copy(root):
    """把当前 keel/ 复制成"新模板"（与真实仓库同构）。"""
    tpl = os.path.join(root, "tpl")
    os.makedirs(tpl, exist_ok=True)
    shutil.copytree(KEEL, os.path.join(tpl, "keel"))
    return tpl


def assert_true(cond, msg):
    assert cond, msg


# ---------------- 用例 ----------------
@case("正常升级：内核覆盖 / 新增补齐 / 版本合并")
def t_normal(root):
    tgt = make_target(root, "3.4.11")
    tpl = template_copy(root)
    before_rules = read(os.path.join(tgt, "keel/checks/rules.md"))
    before_const = read(os.path.join(tgt, "keel/CONSTITUTION.md"))
    rc, out = run_upgrade(["--target", tgt, "--from", tpl, "--skip-test-lint"], root)
    assert_true(rc == 0, "退出码应为 0，实际 %d\n%s" % (rc, out[-800:]))
    assert_true(version_of(os.path.join(tgt, "keel")) == version_of(os.path.join(tpl, "keel")),
                "版本未合并：" + version_of(os.path.join(tgt, "keel")))
    lint = read(os.path.join(tgt, "keel/checks/keel-lint.sh"))
    assert_true("OLD-KERNEL-MARK" not in lint, "旧内核标记未被覆盖")
    assert_true(os.path.isfile(os.path.join(tgt, "keel/checks/retrieval/keel-search.py")),
                "新增内核文件 retrieval/keel-search.py 未补齐")
    assert_true(read(os.path.join(tgt, "keel/checks/rules.md")) == before_rules, "采用方 rules.md 被改")
    assert_true(read(os.path.join(tgt, "keel/CONSTITUTION.md")) == before_const, "采用方 CONSTITUTION 被改")
    assert_true("keel-lint …" in out and "0 fail" in out, "升级前门禁未显示 lint")
    assert_true("预算：固定成本" in out, "预算门禁未显示固定成本")


@case("跨多个版本升级（3.3.0 → 当前）")
def t_multi(root):
    tgt = make_target(root, "3.3.0")
    tpl = template_copy(root)
    rc, out = run_upgrade(["--target", tgt, "--from", tpl, "--skip-test-lint"], root)
    assert_true(rc == 0, "跨版本升级应成功，实际 %d\n%s" % (rc, out[-800:]))
    assert_true(version_of(os.path.join(tgt, "keel")) == version_of(os.path.join(tpl, "keel")),
                "跨版本后版本号不对")
    assert_true(os.path.isfile(os.path.join(tgt, "keel/checks/retrieval/keel-search.py")),
                "跨版本未补齐新增文件")


@case("采用方自定义被保留：rules / CONSTITUTION / NOW / INDEX 路由表")
def t_preserve(root):
    tgt = make_target(root, "3.4.11")
    tpl = template_copy(root)
    write(os.path.join(tgt, "keel/NOW.md"), read(os.path.join(tgt, "keel/NOW.md")) + "\n## 我的进度\n- 自建内容\n")
    idx = os.path.join(tgt, "keel/INDEX.md")
    # 改路由表一行的一列（不新增死链——新增无效行会被升级前 lint 正确拦下）
    write(idx, read(idx).replace("当前焦点、下一步与阻塞", "我的私有焦点"))
    rc, out = run_upgrade(["--target", tgt, "--from", tpl, "--skip-test-lint"], root)
    assert_true(rc == 0, "应成功，实际 %d\n%s" % (rc, out[-600:]))
    keep = read(idx)
    assert_true("自建内容" in read(os.path.join(tgt, "keel/NOW.md")), "NOW.md 自定义被覆盖")
    assert_true("我的私有焦点" in keep, "INDEX 路由表被覆盖")
    assert_true(("keel-version: " + version_of(os.path.join(tpl, "keel"))) in keep, "INDEX 版本行未合并")


@case("升级后门禁失败 → 自动回滚（exit 3）")
def t_rollback(root):
    tgt = make_target(root, "3.4.11")
    tpl = template_copy(root)
    # 造一个"升级后必然 lint 失败"的新模板
    write(os.path.join(tpl, "keel/checks/keel-lint.sh"),
          '#!/usr/bin/env bash\necho "❌ 故意坏的 lint"\nexit 1\n')
    p = subprocess.run([BASH, os.path.join(tpl, "keel/checks/keel-upgrade.sh"),
                        "--regen-manifest", os.path.join(tpl, "keel")],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert_true(p.returncode == 0, "坏模板 regen 失败: " + p.stdout.decode("utf-8", "replace"))
    rc, out = run_upgrade(["--target", tgt, "--from", tpl, "--skip-test-lint"], root)
    assert_true(rc == 3, "应回滚并 exit 3，实际 %d\n%s" % (rc, out[-800:]))
    assert_true(version_of(os.path.join(tgt, "keel")) == "3.4.11", "回滚后版本应回到 3.4.11")
    assert_true("故意坏的 lint" not in read(os.path.join(tgt, "keel/checks/keel-lint.sh")),
                "回滚后内核文件未还原")


@case("幂等：重复执行 → 无需升级，且不新增备份")
def t_idempotent(root):
    tgt = make_target(root, "3.4.11")
    tpl = template_copy(root)
    rc, _ = run_upgrade(["--target", tgt, "--from", tpl, "--skip-test-lint"], root)
    assert_true(rc == 0, "首次升级失败")
    bk = os.path.join(tgt, ".keel-backup")
    n1 = len([d for d in os.listdir(bk) if os.path.isdir(os.path.join(bk, d))])
    snapshot = {}
    for dirpath, _, files in os.walk(os.path.join(tgt, "keel")):
        for f in files:
            p = os.path.join(dirpath, f)
            snapshot[p] = (os.path.getsize(p), os.path.getmtime(p))
    rc, out = run_upgrade(["--target", tgt, "--from", tpl, "--skip-test-lint"], root)
    assert_true(rc == 0, "重复执行应 exit 0，实际 %d" % rc)
    assert_true("无需升级" in out, "重复执行未给出「无需升级」")
    n2 = len([d for d in os.listdir(bk) if os.path.isdir(os.path.join(bk, d))])
    assert_true(n1 == n2, "重复执行新增了备份：%d → %d" % (n1, n2))
    for p, sig in snapshot.items():
        assert_true((os.path.getsize(p), os.path.getmtime(p)) == sig, "重复执行改动了文件: " + p)


@case("已是目标版本：明确「无需升级」")
def t_same(root):
    tpl = template_copy(root)
    tgt = os.path.join(root, "proj")
    os.makedirs(tgt, exist_ok=True)
    shutil.copytree(os.path.join(tpl, "keel"), os.path.join(tgt, "keel"))
    write(os.path.join(tgt, "AGENTS.md"), "# test\n" + ANCHOR + "\n")
    rc, out = run_upgrade(["--target", tgt, "--from", tpl, "--skip-test-lint"], root)
    assert_true(rc == 0, "已是目标版本应 exit 0")
    assert_true("无需升级" in out, "未给出「无需升级」")
    assert_true(not os.path.isdir(os.path.join(tgt, ".keel-backup")), "无需升级却创建了备份")


@case("本地修改过的内核文件：备份并告警")
def t_modified(root):
    tgt = make_target(root, "3.4.11")
    tpl = template_copy(root)
    # 在旧 manifest 之外再改一次内核文件 → 应被识别为"本地修改"
    with open(os.path.join(tgt, "keel/checks/keel-lint.sh"), "a", encoding="utf-8") as fh:
        fh.write("\n# LOCAL-EDIT\n")
    rc, out = run_upgrade(["--target", tgt, "--from", tpl, "--skip-test-lint"], root)
    assert_true(rc == 0, "应成功，实际 %d\n%s" % (rc, out[-600:]))
    assert_true("本地有改动" in out, "未告警本地修改")
    bkdirs = [d for d in os.listdir(os.path.join(tgt, ".keel-backup"))
              if os.path.isdir(os.path.join(tgt, ".keel-backup", d))]
    assert_true(all(os.path.isdir(os.path.join(tgt, ".keel-backup", d, "local-mod")) for d in bkdirs),
                "缺 local-mod 备份目录")
    saved = os.path.join(tgt, ".keel-backup", bkdirs[0], "local-mod/checks/keel-lint.sh")
    assert_true(os.path.isfile(saved) and "LOCAL-EDIT" in read(saved), "本地修改未另存")


@case("dry-run：零改动")
def t_dry(root):
    tgt = make_target(root, "3.4.11")
    tpl = template_copy(root)
    rc, out = run_upgrade(["--target", tgt, "--from", tpl, "--dry-run"], root)
    assert_true(rc == 0, "dry-run 应 exit 0")
    assert_true("dry-run" in out and "未改动任何文件" in out, "dry-run 输出不明确")
    assert_true(not os.path.isdir(os.path.join(tgt, ".keel-backup")), "dry-run 创建了备份")
    assert_true(version_of(os.path.join(tgt, "keel")) == "3.4.11", "dry-run 改了版本号")


@case("manifest 校验和与模板实际文件一致（防清单腐烂）")
def t_manifest(_root):
    rc, out = run_upgrade(["--check-manifest", KEEL], os.path.dirname(KEEL))
    assert_true(rc == 0, "模板 manifest 与实际文件不一致（rc=%d）：\n%s" % (rc, out))
    assert_true("manifest 与实际文件一致" in out, "校验器没打印结论：\n" + out)


@case("manifest 守卫：改 kernel 不改清单 → 判死；重算后 → 通过")
def t_manifest_guard(root):
    tpl = template_copy(root)
    k = os.path.join(tpl, "keel/checks/keel-lint.sh")
    with open(k, "a", encoding="utf-8") as fh:
        fh.write("\n# DRIFT-MARK\n")
    rc, out = run_upgrade(["--check-manifest", os.path.join(tpl, "keel")], root)
    assert_true(rc == 1, "改过 kernel 却未判死（rc=%d）：\n%s" % (rc, out))
    assert_true("checks/keel-lint.sh" in out, "没指出是哪个文件漂移：\n" + out)
    assert_true("期望" in out and "实际" in out, "没给出期望/实际哈希：\n" + out)
    rc, out = run_upgrade(["--regen-manifest", os.path.join(tpl, "keel")], root)
    assert_true(rc == 0, "重算 manifest 失败（rc=%d）：\n%s" % (rc, out))
    rc, out = run_upgrade(["--check-manifest", os.path.join(tpl, "keel")], root)
    assert_true(rc == 0, "重算后仍不一致（rc=%d）：\n%s" % (rc, out))


@case("门禁全量跑：升级前后 lint + test-lint")
def t_full_gates(root):
    tgt = make_target(root, "3.4.11")
    # 造旧 fixture 时删掉了 retrieval，但要保证 test-lint 能跑：补齐 fixture 自带的
    assert_true(os.path.isfile(os.path.join(tgt, "keel/checks/test-lint.sh")), "fixture 缺 test-lint")
    tpl = template_copy(root)
    rc, out = run_upgrade(["--target", tgt, "--from", tpl], root)   # 不加 --skip-test-lint
    assert_true(rc == 0, "全量门禁升级应成功，实际 %d\n%s" % (rc, out[-1200:]))
    assert_true(out.count("test-lint …") == 2, "升级前后各应跑一次 test-lint")
    assert_true("✅ 通过" in out, "test-lint 未通过")


def main():
    verbose = "-v" in sys.argv or "--verbose" in sys.argv
    keep = "--keep" in sys.argv
    if not os.path.isfile(UPGRADE):
        print("❌ 找不到 %s" % UPGRADE)
        return 1

    root = tempfile.mkdtemp(prefix="keel-test-upgrade-")
    print("keel-upgrade 自测 · 用例 %d 例 · 临时目录 %s" % (len(CASES), root))
    print("=" * 76)
    ok = bad = 0
    for name, fn in CASES:
        case_root = os.path.join(root, "c%02d" % (ok + bad))
        os.makedirs(case_root, exist_ok=True)
        try:
            fn(case_root)
            print("[PASS] %s" % name)
            ok += 1
        except AssertionError as e:
            print("[FAIL] %s" % name)
            print("       %s" % str(e).replace("\n", "\n       ")[:1200])
            bad += 1
        except Exception as e:      # noqa: BLE001 —— 自测里任何异常都必须报成失败，不能崩
            print("[FAIL] %s" % name)
            print("       %s: %s" % (type(e).__name__, e))
            bad += 1
        if verbose:
            print("       （用例目录 %s）" % case_root)

    print("=" * 76)
    if bad == 0:
        print("✅ 升级自测通过：%d/%d" % (ok, ok + bad))
    else:
        print("❌ 升级自测失败：%d 项未通过（共 %d 项）" % (bad, ok + bad))
    if keep:
        print("   临时目录保留：%s" % root)
    else:
        shutil.rmtree(root, ignore_errors=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
