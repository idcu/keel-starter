#!/usr/bin/env python3
"""test-wiring.py —— 入口级接线审计（DESIGN.md §12.3 / 本轮新增）

用法：
    python3 keel/checks/wiring/test-wiring.py [--out wiring.json] [-v]
    bash    keel/checks/wiring/test-wiring.sh [--out wiring.json] [-v]

做什么：为每一个 CLI / 发布入口建一条**判死用例**——不是证明"它跑完了"，
而是证明"它被真调用，且它坏掉时套件会红"。逐入口登记在 ENTRANCES，
每条用例断言的是**具体效果**（退出码 + 输出片段 + 磁盘上发生的改变），
不是"命令返回了"。

为什么需要它：v3.14.0 抓到的三个缺陷全部同型——**判据存在，但某条调用路径上
没被调用**：
    ① `check-verify-report.py --report x --repo y`（无 --claims）静默 exit 0；
    ② `--repo` 按仓库根拼路径，少了一层 `keel/`，四个判据文件全判"不存在"；
    ③ 上面两条的 CLI 级用例此前不存在（函数级用例测不到接线）。
判据账本只能证明"有用例"，证明不了"入口被调用"。本套件补的就是这一层，
并把结果写成机器可读的入口—用例—覆盖矩阵（wiring=0 显式列出，不许沉默）。

退出码：0 = 全部入口有判死用例且用例通过；1 = 有用例失败；
        2 = 环境/用法错误（缺 python3 / 缺 git）。
"""

import argparse
import concurrent.futures as futures
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
KEEL = os.path.dirname(os.path.dirname(HERE))       # keel/
PROJECT = os.path.dirname(KEEL)
PROJECT_ORIG = PROJECT


def _release_src():
    """发布脚本只存在于规格仓，不随 keel/ 分发。找不到 = 本入口不适用（n/a），
    不是「没判死用例」——两者在矩阵里必须分开写。"""
    for d in (PROJECT_ORIG, os.path.dirname(PROJECT_ORIG), PROJECT):
        p = os.path.join(d, "scripts", "release.sh")
        if os.path.isfile(p):
            return p
    return None


RELEASE_SRC = _release_src()
BASH = shutil.which("bash") or "bash"
PY = sys.executable

ANCHOR = "任何任务开始前，先读 keel/INDEX.md 与其中指向的 NOW.md，并遵守 INDEX.md 里的检索协议。"
REQUIRED_RELS = ["checks/keel-lint.sh", "checks/test-lint.py",
                 "checks/verify/checks-ledger.py", "checks/verify/verify.py"]


def _shipable(keel_dir):
    try:
        with open(os.path.join(keel_dir, "INDEX.md"), encoding="utf-8") as fh:
            return "../" not in fh.read()
    except OSError:
        return False


# 规格仓里的 keel/ 引用仓外文件，不能单独分发给 fixture；改用同级发布模板。
# 两仓内核逐字节一致，接线审计与用哪一份无关，但 fixture 必须能独立通过门禁。
if not _shipable(KEEL):
    _sib = os.path.normpath(os.path.join(KEEL, "..", "keel-starter", "keel"))
    if _shipable(_sib):
        KEEL = _sib
        PROJECT = os.path.dirname(KEEL)
LINT = os.path.join(KEEL, "checks", "keel-lint.sh")
INSTALL = os.path.join(KEEL, "checks", "install.sh")
UPGRADE = os.path.join(KEEL, "checks", "keel-upgrade.sh")
TESTLINT = os.path.join(KEEL, "checks", "test-lint.py")
MATRIX = os.path.join(KEEL, "checks", "matrix", "test-upgrade-matrix.py")
FAULTS = os.path.join(KEEL, "checks", "test-faults.py")
LEDGER = os.path.join(KEEL, "checks", "verify", "checks-ledger.py")
CVR = os.path.join(KEEL, "checks", "verify", "check-verify-report.py")
VERIFY_SH = os.path.join(KEEL, "checks", "verify", "verify.sh")


# ---------------- 基础设施 ----------------
def read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)


def sh(args, cwd=None, env=None, timeout=300):
    e = dict(os.environ)
    e.pop("KEEL_UPGRADE_BOOTSTRAPPED", None)
    if env:
        e.update(env)
    try:
        p = subprocess.run(args, cwd=cwd, env=e, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=timeout)
        return p.returncode, p.stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired as exc:
        return 124, (exc.stdout or b"").decode("utf-8", "replace") + "\n[超时]"


def version_of(keel_dir):
    for line in read(os.path.join(keel_dir, "INDEX.md")).splitlines():
        if line.startswith("keel-version:"):
            return line.split(":", 1)[1].strip()
    return ""


def tree_sig(keel_dir):
    import hashlib
    sig = {}
    for dp, _, fs in os.walk(keel_dir):
        for f in fs:
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, keel_dir)
            with open(p, "rb") as fh:
                sig[rel] = (hashlib.sha256(fh.read()).hexdigest(),
                            os.stat(p).st_mode & 0o777)
    return sig


def git(repo, *args):
    p = subprocess.run(["git", "-C", repo] + list(args), stdout=subprocess.PIPE,
                       stderr=subprocess.DEVNULL)
    return p.returncode, p.stdout.decode("utf-8", "replace").strip()


def git_init(repo, branch="main"):
    os.makedirs(repo, exist_ok=True)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "t@t")
    git(repo, "config", "user.name", "t")
    git(repo, "symbolic-ref", "HEAD", "refs/heads/" + branch)


def git_commit(repo, msg="init"):
    git(repo, "add", "-A")
    return git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
               "commit", "-qm", msg)[0] == 0


def make_target(root, version="3.4.11"):
    """旧版本采用方仓库：模板副本 + 降版本 + 旧内核标记 + 锚点。"""
    tgt = os.path.join(root, "proj")
    shutil.copytree(KEEL, os.path.join(tgt, "keel"))
    write(os.path.join(tgt, "AGENTS.md"), "# test\n" + ANCHOR + "\n")
    idx = os.path.join(tgt, "keel/INDEX.md")
    write(idx, "\n".join(("keel-version: " + version) if l.startswith("keel-version:")
                         else l for l in read(idx).splitlines()) + "\n")
    with open(os.path.join(tgt, "keel/checks/keel-lint.sh"), "a", encoding="utf-8") as fh:
        fh.write("\n# OLD-KERNEL-MARK\n")
    rc, out = sh([BASH, os.path.join(tgt, "keel/checks/keel-upgrade.sh"),
                  "--regen-manifest", os.path.join(tgt, "keel")])
    assert rc == 0, "建 fixture 失败：%s" % out[-400:]
    return tgt


def template_copy(root):
    tpl = os.path.join(root, "tpl")
    shutil.copytree(KEEL, os.path.join(tpl, "keel"))
    return tpl


def pending_path(tgt):
    return os.path.join(tgt, ".keel-upgrade.pending")


def backup_dirs(tgt):
    base = os.path.join(tgt, ".keel-backup")
    if not os.path.isdir(base):
        return []
    return [os.path.join(base, d) for d in sorted(os.listdir(base))]


# ---------------- 用例注册 ----------------
# ENTRANCES: (编号, 入口描述, 覆盖它的用例编号, 缺失原因)
# 缺失原因非空 = wiring=0（该入口没有判死用例），**必须显式列出**。
ENTRANCES = [
    ("E01", "keel-lint.sh · 相对 / 绝对 / . / 空格+中文 四种入参", "W01", ""),
    ("E02", "keel-lint.sh · 目录不存在（exit 2）", "W02", ""),
    ("E03", "install.sh · 全新安装 + --with-anchor", "W03", ""),
    ("E04", "install.sh · 全新安装缺锚点 → exit 1", "W04", ""),
    ("E05", "install.sh · 已有 keel → 就地升级（两阶段引导）", "W05", ""),
    ("E06", "install.sh · .keel-bootstrap.pending 清理", "W05", ""),
    ("E07", "install.sh · .keel-upgrade.pending → 目标引擎 --resume", "W05", ""),
    ("E08", "install.sh · --ref 缺值（exit 2）", "W06", ""),
    ("E09", "install.sh · --ref 拉不到（exit 2，不回落到 main）", "W07", ""),
    ("E10", "keel-upgrade.sh · --dry-run 零改动", "W08", ""),
    ("E11", "keel-upgrade.sh · --from 两阶段升级", "W09", ""),
    ("E12", "keel-upgrade.sh · --resume 断点续跑", "W10", ""),
    ("E13", "keel-upgrade.sh · --rollback 整目录回滚", "W11", ""),
    ("E14", "keel-upgrade.sh · --regen-manifest / --check-manifest", "W12", ""),
    ("E15", "restore.sh（备份阶段动态生成）直接回滚", "W13", ""),
    ("E16", "verify.sh + verify.py 套件调度（失败必须传播）", "W14", ""),
    ("E17", "check-verify-report.py · --selftest", "W15", ""),
    ("E18", "check-verify-report.py · 无 --claims 也校验 provenance", "W16", ""),
    ("E19", "check-verify-report.py · --repo 按 <repo>/keel/ 布局解析", "W17", ""),
    ("E20", "check-verify-report.py · --claims + --summary", "W18", ""),
    ("E21", "checks-ledger.py · --selftest", "W19", ""),
    ("E22", "checks-ledger.py · --json / --out / --cases / --design", "W20", ""),
    ("E23", "test-upgrade-matrix.py · current + REG-1 格", "W21", ""),
    ("E24", "test-faults.py · 判死自检 + 环境分类", "W22", ""),
    ("E25", "release.sh · dry-run 顺序输出（先发布仓后项目仓）", "W23", ""),
    ("E26", "release.sh · 脏树拦截（exit 1）", "W24", ""),
]

CASES = []


class NotApplicable(Exception):
    """入口在当前仓库不存在（例如发布脚本属规格仓、不随 keel/ 分发）。"""


def wcase(cid, name, entry, fn):
    CASES.append((cid, name, entry, fn))


def _assert(cond, msg):
    assert cond, msg


def _contains(out, *words):
    missing = [w for w in words if w not in out]
    _assert(not missing, "输出缺 %s" % "、".join(missing))


# ---------------- W01 / W02：keel-lint.sh ----------------
def lint_fixture(root):
    t = os.path.join(root, "repo")
    shutil.copytree(KEEL, os.path.join(t, "keel"))
    write(os.path.join(t, "AGENTS.md"), ANCHOR + "\n")
    return t


def w01(root):
    t = lint_fixture(root)
    rc, out = sh([BASH, LINT, "keel"], cwd=t)
    _assert(rc == 0, "合法基线应 0 fail，实际 %d\n%s" % (rc, out[-500:]))
    # 注入一条**只在前两种入参下才会命中**的违规（行数超限）
    app = os.path.join(t, "keel/INDEX.md")
    with open(app, "a", encoding="utf-8") as fh:
        fh.write("".join("- r%d\n" % i for i in range(120)))
    forms = [
        ("相对 keel", [BASH, LINT, "keel"], t),
        ("绝对路径", [BASH, LINT, os.path.join(t, "keel")], t),
        ("点号 .", [BASH, LINT, "."], os.path.join(t, "keel")),
    ]
    spaced = os.path.join(root, " repo 有空格 中文")
    shutil.copytree(t, spaced)
    forms.append(("空格+中文", [BASH, LINT, "keel"], spaced))
    bad = []
    for name, cmd, cwd in forms:
        rc, out = sh(cmd, cwd=cwd)
        if rc != 1 or "超行数" not in out:
            bad.append("%s: rc=%d 超行数=%s" % (name, rc, "超行数" in out))
    _assert(not bad, "入参形式未真正进入同一判据 → %s" % bad)
    return "4 种入参形式都命中了同一条「超行数」判死"


def w02(root):
    rc, out = sh([BASH, LINT, os.path.join(root, "不存在")])
    _assert(rc == 2, "缺目录应 exit 2，实际 %d" % rc)
    _contains(out, "目录不存在")
    return "缺目录 exit 2 且报「目录不存在」"


# ---------------- W03-W07：install.sh ----------------
def starter_repo(root):
    repo = os.path.join(root, "starter-repo")
    shutil.copytree(KEEL, os.path.join(repo, "keel"))
    git_init(repo)
    _assert(git_commit(repo), "本地模板仓提交失败")
    return repo


def run_install(repo, target, *args, **kw):
    return sh([BASH, INSTALL, target] + list(args),
              env={"KEEL_INSTALL_REPO": repo}, **kw)


def w03(root):
    repo = starter_repo(root)
    tgt = os.path.join(root, "new-proj")
    os.makedirs(tgt)
    rc, out = run_install(repo, tgt, "--with-anchor")
    _assert(rc == 0, "全新安装应成功，实际 %d\n%s" % (rc, out[-800:]))
    _contains(out, "✅ 装好了", "AGENTS.md", "锚点")
    _assert(version_of(os.path.join(tgt, "keel")) == version_of(KEEL),
            "安装后的版本不是模板版本")
    _assert(ANCHOR in read(os.path.join(tgt, "AGENTS.md")), "锚点未写入")
    return "全新安装 rc=0、版本与模板一致、锚点已落盘"


def w04(root):
    repo = starter_repo(root)
    tgt = os.path.join(root, "new-proj-no-anchor")
    os.makedirs(tgt)
    rc, out = run_install(repo, tgt)
    _assert(rc == 1, "缺锚点时 install 应 exit 1（lint 未通过），实际 %d" % rc)
    _contains(out, "❌ lint 未通过", "缺的是**点火锚点**")
    _assert(not os.path.exists(os.path.join(tgt, "AGENTS.md")),
            "默认不应写用户的 AGENTS.md")
    return "缺锚点 → rc=1，且失败原因来自 lint 原文（不是猜的）"


def w05(root):
    repo = starter_repo(root)
    tgt = make_target(root, "3.4.11")
    tpl = template_copy(root)
    # 先制造一个真实的升级断点：目标版本引擎在 backup 后被杀
    rc, out = sh([BASH, os.path.join(tpl, "keel/checks/keel-upgrade.sh"),
                  "--target", tgt, "--from", tpl, "--skip-test-lint"],
                 cwd=root, env={"KEEL_UPGRADE_TEST_HOOKS": "1",
                                "KEEL_UPGRADE_FAULT": "after:backup"})
    _assert(rc != 0, "故障注入应中断升级，实际 %d\n%s" % (rc, out[-400:]))
    _assert(os.path.isfile(pending_path(tgt)), "中断后未留下升级断点")
    write(os.path.join(tgt, ".keel-bootstrap.pending"), "stale\n")
    rc, out = run_install(repo, tgt)
    _assert(rc == 0, "就地升级应成功，实际 %d\n%s" % (rc, out[-900:]))
    _contains(out, "就地升级", "清理上次未完成的引导标记",
              "检测到未完成的升级断点", "目标版本引擎 --resume")
    _assert(version_of(os.path.join(tgt, "keel")) == version_of(KEEL),
            "就地升级后版本未更新")
    _assert(not os.path.exists(pending_path(tgt)), "升级成功后断点未清除")
    _assert(not os.path.exists(os.path.join(tgt, ".keel-bootstrap.pending")),
            "引导标记未清理")
    return "EXISTING + bootstrap pending + upgrade pending(--resume) 三条分支都被真调用"


def w06(root):
    rc, out = sh([BASH, INSTALL, os.path.join(root, "tgt"), "--ref"])
    _assert(rc == 2, "--ref 缺值应 exit 2，实际 %d" % rc)
    _contains(out, "--ref 后面要跟版本号")
    return "--ref 缺值 rc=2"


def w07(root):
    repo = starter_repo(root)
    tgt = os.path.join(root, "tgt-bogus-ref")
    os.makedirs(tgt)
    rc, out = run_install(repo, tgt, "--ref", "v9.9.9")
    _assert(rc == 2, "显式 --ref 拉不到应 exit 2（不许回落 main），实际 %d\n%s"
            % (rc, out[-600:]))
    _contains(out, "拉取失败")
    _assert("已复制 keel/" not in out, "拉取失败后仍复制了 keel/（静默回落？）")
    _assert(not os.path.isdir(os.path.join(tgt, "keel")), "失败后目标被改动")
    return "显式 --ref 拉不到 → rc=2 且目标零改动（无回落）"


# ---------------- W08-W13：keel-upgrade.sh ----------------
def w08(root):
    tgt = make_target(root, "3.4.11")
    tpl = template_copy(root)
    before = tree_sig(os.path.join(tgt, "keel"))
    rc, out = sh([BASH, UPGRADE, "--target", tgt, "--from", tpl, "--dry-run"])
    _assert(rc == 0, "dry-run 应 exit 0，实际 %d\n%s" % (rc, out[-500:]))
    _contains(out, "dry-run")
    _assert(tree_sig(os.path.join(tgt, "keel")) == before, "dry-run 改了文件")
    _assert(not os.path.isdir(os.path.join(tgt, ".keel-backup")), "dry-run 建了备份")
    return "dry-run rc=0、零改动、零备份"


def w09(root):
    tgt = make_target(root, "3.4.11")
    tpl = template_copy(root)
    rc, out = sh([BASH, UPGRADE, "--target", tgt, "--from", tpl,
                  "--skip-test-lint"])
    _assert(rc == 0, "--from 升级应成功，实际 %d\n%s" % (rc, out[-800:]))
    _assert(version_of(os.path.join(tgt, "keel")) == version_of(KEEL),
            "升级后版本未更新")
    _assert("OLD-KERNEL-MARK" not in read(os.path.join(tgt, "keel/checks/keel-lint.sh")),
            "内核未被覆盖")
    return "--from 两阶段升级 rc=0、版本与内核均已更新"


def w10(root):
    tgt = make_target(root, "3.4.11")
    tpl = template_copy(root)
    rc, out = sh([BASH, UPGRADE, "--target", tgt, "--from", tpl,
                  "--skip-test-lint"], env={"KEEL_UPGRADE_TEST_HOOKS": "1",
                                            "KEEL_UPGRADE_FAULT": "after:file:3"})
    _assert(rc != 0, "故障注入应中断升级")
    _assert(os.path.isfile(pending_path(tgt)), "未留下断点")
    rc, out = sh([BASH, UPGRADE, "--target", tgt, "--from", tpl,
                  "--skip-test-lint", "--resume"])
    _assert(rc == 0, "--resume 应成功，实际 %d\n%s" % (rc, out[-800:]))
    _assert(not os.path.exists(pending_path(tgt)), "续跑后断点未清除")
    _assert(version_of(os.path.join(tgt, "keel")) == version_of(KEEL),
            "续跑后版本未更新")
    return "--resume 从第 3 个文件处续跑成功并清除断点"


def w11(root):
    tgt = make_target(root, "3.4.11")
    tpl = template_copy(root)
    before = tree_sig(os.path.join(tgt, "keel"))
    rc, _ = sh([BASH, UPGRADE, "--target", tgt, "--from", tpl, "--skip-test-lint"],
               env={"KEEL_UPGRADE_TEST_HOOKS": "1",
                    "KEEL_UPGRADE_FAULT": "after:file:3"})
    _assert(rc != 0, "故障注入应中断升级")
    rc, out = sh([BASH, UPGRADE, "--target", tgt, "--rollback"])
    _assert(rc == 0, "--rollback 应成功，实际 %d\n%s" % (rc, out[-600:]))
    _assert(tree_sig(os.path.join(tgt, "keel")) == before, "回滚后字节/权限不一致")
    _assert(not os.path.exists(pending_path(tgt)), "回滚后断点未清除")
    return "--rollback 恢复原字节与权限"


def w12(root):
    tgt = make_target(root, "3.4.11")
    k = os.path.join(tgt, "keel")
    manifest = os.path.join(k, "checks/manifest.tsv")
    lines = read(manifest).splitlines()
    idx = next(i for i, l in enumerate(lines)
               if l.startswith("kernel\t") and len(l.split("\t")) >= 4)
    parts = lines[idx].split("\t")
    parts[3] = "0" * 64          # 把一个已存在文件的 sha256 改成错值
    lines[idx] = "\t".join(parts)
    write(manifest, "\n".join(lines) + "\n")
    rc, out = sh([BASH, UPGRADE, "--check-manifest", k])
    _assert(rc != 0, "篡改 manifest 后 --check-manifest 应变红，实际 %d\n%s"
            % (rc, out[-500:]))
    rc, out = sh([BASH, UPGRADE, "--regen-manifest", k])
    _assert(rc == 0, "--regen-manifest 应成功，实际 %d" % rc)
    rc, out = sh([BASH, UPGRADE, "--check-manifest", k])
    _assert(rc == 0, "重算 manifest 后应通过，实际 %d\n%s" % (rc, out[-400:]))
    return "篡改 → 红；regen → 绿"


def w13(root):
    tgt = make_target(root, "3.4.11")
    tpl = template_copy(root)
    before = tree_sig(os.path.join(tgt, "keel"))
    rc, _ = sh([BASH, UPGRADE, "--target", tgt, "--from", tpl, "--skip-test-lint"],
               env={"KEEL_UPGRADE_TEST_HOOKS": "1",
                    "KEEL_UPGRADE_FAULT": "after:file:3"})
    _assert(rc != 0, "故障注入应中断升级")
    bks = [b for b in backup_dirs(tgt) if os.path.isfile(os.path.join(b, "restore.sh"))]
    _assert(bks, "备份阶段未生成 restore.sh")
    rs = os.path.join(bks[-1], "restore.sh")
    _assert(os.access(rs, os.X_OK), "restore.sh 不可执行")
    rc, out = sh([BASH, rs])
    _assert(rc == 0, "直接执行 restore.sh 应成功，实际 %d\n%s" % (rc, out[-500:]))
    _assert(tree_sig(os.path.join(tgt, "keel")) == before,
            "restore.sh 未恢复原字节/权限")
    return "restore.sh 由备份生成、可执行、直接跑可回滚"


# ---------------- W14：verify.sh + verify.py 调度 ----------------
def w14(root):
    rep = os.path.join(root, "verify-ok.json")
    rc, out = sh([BASH, VERIFY_SH, "--suites", "lint", "--out", rep], cwd=PROJECT)
    _assert(rc == 0, "verify 的 lint 套件应通过，实际 %d\n%s" % (rc, out[-600:]))
    data = json.load(open(rep, encoding="utf-8"))
    lint = [s for s in data["suites"] if s["name"] == "lint"][0]
    _assert(lint["status"] == "PASS", "清单未记录 lint PASS")
    # 判死：把套件命令弄坏，verify 必须失败并传播（而不是静默跳过）
    broken = os.path.join(root, "broken")
    shutil.copytree(KEEL, os.path.join(broken, "keel"))
    write(os.path.join(broken, "keel/checks/keel-lint.sh"),
          "#!/usr/bin/env bash\nexit 1\n")
    rep2 = os.path.join(root, "verify-broken.json")
    rc, out = sh([BASH, os.path.join(broken, "keel/checks/verify/verify.sh"),
                  "--suites", "lint", "--out", rep2], cwd=broken)
    _assert(rc == 1, "套件失败时 verify 应 exit 1，实际 %d\n%s" % (rc, out[-600:]))
    data = json.load(open(rep2, encoding="utf-8"))
    lint = [s for s in data["suites"] if s["name"] == "lint"][0]
    _assert(lint["status"] == "FAIL" and lint["failed"] == 1,
            "套件失败未记入清单（静默绿）")
    return "verify.sh → verify.py → 套件命令，失败会传播成 FAIL/exit 1"


# ---------------- W15-W18：check-verify-report.py ----------------
def prov_fixture(root, nested=True):
    repo = os.path.join(root, "repo-nested" if nested else "repo-flat")
    base = os.path.join(repo, "keel") if nested else repo
    for rel in REQUIRED_RELS:
        write(os.path.join(base, rel), read(os.path.join(KEEL, rel)))
    git_init(repo)
    _assert(git_commit(repo), "provenance fixture 提交失败")
    return repo, base


def min_report(repo, base):
    import hashlib
    shas = {rel: hashlib.sha256(open(os.path.join(base, rel), "rb").read()).hexdigest()
            for rel in REQUIRED_RELS}
    return {
        "schema": 1,
        "environment": {"engine_version": "9.9.9", "platform": "test"},
        "provenance": {
            "commit": git(repo, "rev-parse", "HEAD")[1],
            "dirty": False, "dirty_files": 0, "checks_sha256": shas,
            "platform": {"system": "test", "release": "test"},
            "locale": {"LANG": "C.UTF-8"},
            "generated_at": "2026-01-01T00:00:00+08:00",
        },
        "suites": [{"name": "lint", "status": "PASS", "skip_reason": None,
                    "passed": 1, "failed": 0, "skipped": 0, "cases": 1,
                    "duration_s": 0.1}],
        "checks_ledger": {
            "totals": {"numbered": 1, "implemented": 1, "extension": 0,
                       "negative": 1, "positive_only": 0, "none": 0,
                       "coverage_pct_of_numbered": 100.0,
                       "coverage_pct_of_implemented": 100.0,
                       "with_meta": {"denominator": 2, "negative": 2,
                                     "coverage_pct": 100.0},
                       "all": {"denominator": 2, "negative": 2,
                               "coverage_pct": 100.0}},
            "checks": [{"id": "§9.1-1", "coverage": "negative", "cases": 1,
                        "negative_cases": 1}],
            "extras": [{"id": "§9.3-DOC", "kind": "meta", "coverage": "negative",
                        "cases": 1, "negative_cases": 1}],
            "auxiliary": [], "meta": [], "errors": [],
        },
        "wiring": {
            "entrances": [{"id": "E01", "entry": "lint", "case": "W01",
                           "cases": ["W01"], "status": "negative", "reason": None}],
            "cases": [{"id": "W01", "name": "lint 判死", "entry": "E01",
                       "passed": True, "detail": "ok"}],
            "totals": {"entrances": 1, "with_negative": 1, "wiring_zero": 0,
                       "zero_ids": [], "not_applicable": 0,
                       "not_applicable_ids": [], "failed_entrances": [],
                       "cases": 1, "cases_passed": 1},
            "duration_s": 0.1,
        },
        "mutation": {
            "totals": {"mutants": 16, "killed": 15, "survived": 1,
                       "invalid": 0, "score_pct": 93.8},
            "mutants": [], "selected": ["§9.1-1"],
            "excluded": [{"ref": "§9.1-12", "reason": "warn-only，非 fail 级"}],
            "operators": ["delete_fail"],
            "boundary": "抓不到接线错、语义正确但判据放宽未被 fixture 命中、跨文件/跨版本行为",
            "duration_s": 1.0,
        },
        "summary": {"passed": 1, "failed": 0, "skipped": 0, "verified": True},
    }


def cvr_cli(report, repo=None, claims=None, summary=False):
    fd, tmp = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False)
    args = [PY, CVR, "--report", tmp]
    if repo:
        args += ["--repo", repo]
    for c in claims or []:
        args += ["--claims", c]
    if summary:
        args.append("--summary")
    rc, out = sh(args)
    os.remove(tmp)
    return rc, out


def _json_report(root):
    repo, base = prov_fixture(root, nested=True)
    return repo, base, min_report(repo, base)


def w15(root):
    rc, out = sh([PY, CVR, "--selftest"])
    m = re.search(r"判据自检 (\d+)/(\d+)", out)
    _assert(rc == 0 and m, "自检应通过，实际 %d\n%s" % (rc, out[-600:]))
    _assert(int(m.group(1)) == int(m.group(2)), "自检未全过")
    return "自检 %s/%s" % (m.group(1), m.group(2))


def w16(root):
    """回归①：`--report x --repo y` 不带 --claims 时，provenance 校验必须仍被调用。"""
    repo, base, rep = _json_report(root)
    rc, out = cvr_cli(rep, repo=repo)
    _assert(rc == 0, "一致清单（无 claims）应放行，实际 %d\n%s" % (rc, out[-500:]))
    rep["provenance"]["commit"] = "f" * 40
    rc, out = cvr_cli(rep, repo=repo)
    _assert(rc == 1, "commit 不符时无 claims 路径必须判死（v3.14.0 静默绿回归），实际 %d" % rc)
    _contains(out, "不一致", "旧清单冒充新证据")
    return "无 --claims 路径也执行 provenance 校验（旧清单判死）"


def w17(root):
    """回归②：`--repo` 指向仓库根时，判据文件在 <repo>/keel/ 下，不能少一层。"""
    repo, base, rep = _json_report(root)
    rc, out = cvr_cli(rep, repo=repo)
    _assert(rc == 0, "<repo>/keel/ 布局应能解析判据文件，实际 %d\n%s" % (rc, out[-500:]))
    _assert("不存在" not in out, "仍按 <repo>/checks/ 拼路径（少一层 keel/）")
    return "按 <repo>/keel/ 解析四个判据文件"


def w18(root):
    repo, base, rep = _json_report(root)
    ch = os.path.join(root, "CHANGELOG.md")
    write(ch, "## 9.9.9 — 2026-01-01\n\n全部通过。\n")
    rc, out = cvr_cli(rep, repo=repo, claims=[ch], summary=True)
    _assert(rc == 0, "无跳过时「全部通过」应放行，实际 %d\n%s" % (rc, out[-500:]))
    _contains(out, "## 验证状况（verify-report.json）")
    rep["suites"][0]["status"] = "SKIP"
    rep["suites"][0]["skip_reason"] = "测试样本"
    rep["suites"][0]["skipped"] = 1
    rep["summary"] = {"passed": 0, "failed": 0, "skipped": 1, "verified": False}
    rc, out = cvr_cli(rep, repo=repo, claims=[ch])
    _assert(rc == 1, "含 SKIP 时「全部通过」必须判死，实际 %d" % rc)
    _contains(out, "无条件表述")
    return "--claims + --summary 两条路径都生效；含 SKIP 的「全部通过」判死"


# ---------------- W19-W20：checks-ledger.py ----------------
def w19(root):
    rc, out = sh([PY, LEDGER, "--selftest", "--cases", TESTLINT])
    m = re.search(r"判据账本自检 (\d+)/(\d+)", out)
    _assert(rc == 0 and m, "账本自检应通过，实际 %d\n%s" % (rc, out[-600:]))
    _assert(m.group(1) == m.group(2), "账本自检未全过")
    return "账本自检 %s/%s" % (m.group(1), m.group(2))


def w20(root):
    outj = os.path.join(root, "ledger.json")
    args = [PY, LEDGER, "--out", outj, "--cases", TESTLINT]
    design = os.path.join(PROJECT, "DESIGN.md")
    if os.path.isfile(design):
        args += ["--design", design]
    rc, out = sh(args)
    _assert(rc == 0, "账本 CLI 应成功，实际 %d\n%s" % (rc, out[-600:]))
    led = json.load(open(outj, encoding="utf-8"))
    t = led["totals"]
    _assert(t["numbered"] == 19 and t["negative"] >= 1, "账本口径异常: %r" % t)
    _assert(t["with_meta"]["denominator"] >= t["numbered"], "含元检查分母未扩大")
    rc, out = sh([PY, LEDGER, "--cases", os.path.join(root, "缺文件.py")])
    _assert(rc != 0, "缺 cases 文件必须变红，实际 %d\n%s" % (rc, out[-400:]))
    return "--json/--out/--cases/--design 生效；缺 cases 文件变红"


# ---------------- W21-W22：矩阵 / 故障 ----------------
def w21(root):
    rc, out = sh([PY, MATRIX], cwd=PROJECT,
                 env={"KEEL_MATRIX_VERSIONS": "current",
                      "KEEL_MATRIX_NO_INSTALL_CELL": "1",
                      "KEEL_MATRIX_OFFLINE": "1"}, timeout=300)
    _assert(rc == 0, "current + REG-1 两格应通过，实际 %d\n%s" % (rc, out[-900:]))
    _assert("[PASS] current" in out and "[PASS] REG-1" in out,
            "矩阵格未真正产出 PASS 断言\n%s" % out[-600:])
    return "current 与 REG-1 两格被执行并 PASS"


def w22(root):
    # 显式跳过 Docker：接线审计要的是「入口被调用 + 跳过语义不退化成通过」，
    # 不是在这里再跑一遍容器故障注入（那由 verify 的 test-faults 套件负责）。
    rc, out = sh([PY, FAULTS], timeout=300, env={"KEEL_SKIP_DOCKER": "1"})
    _assert(rc == 0, "故障自检应 exit 0（缺 Docker 时为 SKIP），实际 %d\n%s"
            % (rc, out[-700:]))
    _contains(out, "判死自检通过")
    _assert(re.search(r"：\d+ 通过 / \d+ 失败 / \d+ 跳过（未验证）", out),
            "未输出可解析的汇总行")
    return "判死自检 + 环境分类 + 汇总行"


# ---------------- W23-W24：release.sh ----------------
def release_fixture(root, dirty=False):
    if not RELEASE_SRC:
        raise NotApplicable("本仓无 scripts/release.sh（发布链路属规格仓，不随 keel/ 分发）")
    proj = os.path.join(root, "proj")
    sub = os.path.join(proj, "keel-starter")
    os.makedirs(os.path.join(proj, "scripts"))
    write(os.path.join(proj, "scripts/release.sh"), read(RELEASE_SRC))
    shutil.copytree(KEEL, os.path.join(sub, "keel"))
    git_init(sub)
    _assert(git_commit(sub), "发布仓 fixture 提交失败")
    git_init(proj)
    write(os.path.join(proj, ".gitmodules"),
          '[submodule "keel-starter"]\n\tpath = keel-starter\n\turl = ./keel-starter\n')
    sha = git(sub, "rev-parse", "HEAD")[1]
    git(proj, "add", ".gitmodules", "scripts")
    rc = subprocess.run(["git", "-C", proj, "update-index", "--add", "--cacheinfo",
                         "160000,%s,keel-starter" % sha],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert rc.returncode == 0, "无法写入子模块 gitlink"
    _assert(git_commit(proj), "项目仓 fixture 提交失败")
    if dirty:
        write(os.path.join(proj, "未提交.txt"), "x\n")
    return proj


def w23(root):
    proj = release_fixture(root)
    rc, out = sh([BASH, os.path.join(proj, "scripts/release.sh"), "--dry-run"],
                 cwd=proj)
    _assert(rc == 0, "dry-run 应 exit 0，实际 %d\n%s" % (rc, out[-800:]))
    _assert(out.index("① 发布仓") < out.index("② 项目仓"),
            "推送顺序未固定为「先发布仓、后项目仓」")
    _contains(out, "dry-run 未推送")
    return "dry-run 输出顺序正确、未推送"


def w24(root):
    proj = release_fixture(root, dirty=True)
    rc, out = sh([BASH, os.path.join(proj, "scripts/release.sh"), "--dry-run"],
                 cwd=proj)
    _assert(rc == 1, "脏树必须 exit 1，实际 %d\n%s" % (rc, out[-500:]))
    _contains(out, "工作区不干净")
    return "脏树在 dry-run 阶段即被拦（exit 1）"


wcase("W01", "keel-lint 四种入参命中同一判据", "E01", w01)
wcase("W02", "keel-lint 缺目录 exit 2", "E02", w02)
wcase("W03", "install 全新安装 + 锚点", "E03", w03)
wcase("W04", "install 缺锚点 → lint 失败传播", "E04", w04)
wcase("W05", "install 就地升级 + 两个 pending 分支", "E05/E06/E07", w05)
wcase("W06", "install --ref 缺值", "E08", w06)
wcase("W07", "install --ref 拉不到不回落", "E09", w07)
wcase("W08", "upgrade --dry-run 零改动", "E10", w08)
wcase("W09", "upgrade --from 两阶段", "E11", w09)
wcase("W10", "upgrade --resume 断点续跑", "E12", w10)
wcase("W11", "upgrade --rollback 回滚", "E13", w11)
wcase("W12", "upgrade manifest regen/check", "E14", w12)
wcase("W13", "restore.sh 直接回滚", "E15", w13)
wcase("W14", "verify 套件调度失败传播", "E16", w14)
wcase("W15", "check-verify-report 自检", "E17", w15)
wcase("W16", "无 --claims 也校验 provenance", "E18", w16)
wcase("W17", "--repo 按 <repo>/keel/ 解析", "E19", w17)
wcase("W18", "--claims/--summary + 含混文案判死", "E20", w18)
wcase("W19", "checks-ledger 自检", "E21", w19)
wcase("W20", "checks-ledger CLI 与缺文件变红", "E22", w20)
wcase("W21", "矩阵 current + REG-1 格", "E23", w21)
wcase("W22", "故障自检与环境分类", "E24", w22)
wcase("W23", "release dry-run 顺序", "E25", w23)
wcase("W24", "release 脏树拦截", "E26", w24)


def main():
    ap = argparse.ArgumentParser(description="入口级接线审计")
    ap.add_argument("--out", default="")
    ap.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1))
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    for tool in ("git", "python3"):
        if not shutil.which(tool) and tool == "git":
            print("❌ 缺 %s，无法构造接线 fixture" % tool)
            return 2

    root = tempfile.mkdtemp(prefix="keel-wiring-")
    t0 = time.time()
    print("入口接线审计 · 入口 %d 条 · 用例 %d 条 · 并行 %d · 临时目录 %s"
          % (len(ENTRANCES), len(CASES), a.jobs, root))
    print("=" * 78)

    def one(item):
        cid, name, entry, fn = item
        croot = os.path.join(root, cid)
        os.makedirs(croot, exist_ok=True)
        t0c = time.time()
        try:
            msg = fn(croot)
            res = {"id": cid, "name": name, "entry": entry,
                   "passed": True, "status": "pass", "detail": msg}
        except NotApplicable as e:
            res = {"id": cid, "name": name, "entry": entry,
                   "passed": True, "status": "n/a", "detail": str(e)}
        except AssertionError as e:
            res = {"id": cid, "name": name, "entry": entry,
                   "passed": False, "status": "fail", "detail": str(e)[:800]}
        except Exception as e:      # noqa: BLE001
            res = {"id": cid, "name": name, "entry": entry,
                   "passed": False, "status": "fail",
                   "detail": "%s: %s" % (type(e).__name__, e)}
        res["duration_s"] = round(time.time() - t0c, 1)
        return res

    results = {}
    bad = 0
    with futures.ThreadPoolExecutor(max_workers=a.jobs) as ex:
        for res in ex.map(one, CASES):
            cid = res["id"]
            results[cid] = res
            if res["status"] == "pass":
                print("[PASS] %s %-40s %s" % (cid, res["name"], res["detail"]))
            elif res["status"] == "n/a":
                print("[N/A ] %s %-40s %s" % (cid, res["name"], res["detail"]))
            else:
                bad += 1
                print("[FAIL] %s %-40s %s" % (cid, res["name"], res["detail"]))
            if a.verbose:
                print("       （目录 %s，%ss）" % (os.path.join(root, cid),
                                                 res["duration_s"]))

    # ---- 入口矩阵 ----
    ent_rows = []
    for eid, desc, case_ids, reason in ENTRANCES:
        cases = [c for c in case_ids.split("/") if c]
        ok = bool(cases) and all(results.get(c, {}).get("passed") for c in cases)
        na = bool(cases) and all(results.get(c, {}).get("status") == "n/a" for c in cases)
        if not cases:
            status = "none"
        elif na:
            status = "n/a"
        elif not ok:
            status = "failed"
        else:
            status = "negative"
        ent_rows.append({"id": eid, "entry": desc, "cases": cases,
                         "case": case_ids, "status": status,
                         "reason": reason or (results[cases[0]]["detail"]
                                              if na else None)})
    with_neg = sum(1 for r in ent_rows if r["status"] == "negative")
    zeros = [r["id"] for r in ent_rows if r["status"] == "none"]
    not_app = [r["id"] for r in ent_rows if r["status"] == "n/a"]
    failed_rows = [r["id"] for r in ent_rows if r["status"] == "failed"]
    cases_passed = sum(1 for c in results.values() if c["passed"])

    duration = round(time.time() - t0, 1)
    print("=" * 78)
    print("入口矩阵（%d 条入口）" % len(ent_rows))
    for r in ent_rows:
        print("  %-4s %-8s %-52s %s" % (r["id"], r["status"], r["entry"][:52],
                                        r["case"] or ("wiring=0：" + (r["reason"] or "无原因"))))
    print("=" * 78)
    head = "✅ 接线自测通过" if not bad else "❌ 接线自测失败"
    print("%s：%d/%d 入口有判死用例 · %d/%d 用例通过 · wiring=0: %s · n/a: %s · %ss"
          % (head, with_neg, len(ent_rows), cases_passed, len(CASES),
             "、".join(zeros) or "无", "、".join(not_app) or "无", duration))
    if zeros:
        print("   ⚠️  wiring=0 的入口没有判死用例：%s（发行说明不得写「全部接线」）"
              % "、".join(zeros))
    if not_app:
        print("   · 不适用入口（本仓无该脚本）：%s（不是缺用例，矩阵里单列）"
              % "、".join(not_app))
    if failed_rows:
        print("   ❌ 判死用例失败的入口：%s" % "、".join(failed_rows))

    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump({
                "schema": 1,
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "entrances": ent_rows,
                "cases": [results[c[0]] for c in CASES],
                "totals": {
                    "entrances": len(ent_rows),
                    "with_negative": with_neg,
                    "wiring_zero": len(zeros),
                    "zero_ids": zeros,
                    "not_applicable": len(not_app),
                    "not_applicable_ids": not_app,
                    "failed_entrances": failed_rows,
                    "cases": len(CASES),
                    "cases_passed": cases_passed,
                },
                "duration_s": duration,
            }, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        print("   入口矩阵已写入：%s" % a.out)

    shutil.rmtree(root, ignore_errors=True)
    return 1 if (bad or failed_rows) else 0


if __name__ == "__main__":
    sys.exit(main())
