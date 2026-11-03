#!/usr/bin/env python3
"""跨版本升级矩阵（DESIGN.md §12.3 / ADR 0020）

用法：
    bash   keel/checks/test-upgrade-matrix.sh [-v]
    python3 keel/checks/test-upgrade-matrix.py [-v]

做什么：把「起点版本」当成矩阵的一维，逐格验证**旧引擎执行的升级**不因新判据
的新假设而失败。默认格：v3.6.1、v3.7.4、v3.8.0、v3.9.0、current（幂等），外加
v3.4.11（≤3.5.0，没有升级引擎，只能走 install.sh 引导）作为独立用例。
v3.6.1 是 3.6.x 时代的代表格：它的备份布局与引擎分支与 3.7+ 不同，单独一档
用来证明「起点更旧」不会因新判据的新假设而被误判。

每格判据（缺一不算过）：
  ① 无假失败：旧引擎 + 当前模板升级，退出码 0 且打印「升级完成」
  ② 内核文件与当前模板逐字节一致（sha256 + 权限位）
  ③ 采用方自定义文件（NOW.md / decisions/ 下的自建文件）哈希不变
  ④ 门禁绿：升级后 keel-lint 0 fail
  ⑤ 终态五项：版本 / pending 清除 / 备份可回滚 / manifest 一致 / 无临时文件
  ⑥ 可续跑：after:backup 中断 → --resume 续完，结果与一次成功升级逐字节一致
  ⑦ 可回滚：--rollback 后恢复起点版本与升级前字节/权限
current 格只验证幂等（no-op、无新备份、零改动），⑥⑦ 记 N/A。

旧引擎的执行隔离（重要）：≤3.9.x 的引擎用裸 `cp` 覆盖目标文件，包括**正在执行的
自己**（cp 是 truncate 不是 rename），运行中的 bash 会从同 inode 的新内容中间继续
读——实测 3.7.4 崩在收尾（`_rel: unbound variable`）。这是旧实现的自替换缺陷，不是
"新判据的新假设"，所以矩阵把旧引擎复制到临时位置执行，隔离该事故后再验证判据兼容性；
采用方的真实路径是 install.sh / 新引擎（v3.10.0 的交接与 atomic rename 都已覆盖，
test-upgrade 的「自身替换安全」用例单独验证原地执行）。

历史误判回归（REG-1）：旧引擎建的备份目录**没有 restore.sh**（3.8.x 不写它）。
v3.9.0 的终态校验曾要求它存在，导致所有从旧版升上来的采用方被误判失败。
本套件手工构造「旧引擎备份布局 + stage=done」的状态，用当前引擎 --resume，
必须通过并打印「上次升级已完成」；若哪天又有人把 restore.sh 加回判据，这一格立刻红。

快照与缓存（不把历史版本硬编码成巨型 fixture）：
  - 快照来源 = 发布仓的 git tag：`git -C <repo> archive vX.Y.Z`，解包到缓存目录；
  - 缓存默认 ${TMPDIR}/keel-matrix-cache/vX.Y.Z（可用 KEEL_MATRIX_CACHE 指定），
    命中即复用，解包写临时目录再 rename（半成品不会被当成缓存）；
  - 本地没有该 tag 时才尝试 `git fetch --depth 1 origin <tag>`（联网）；
  - 设 KEEL_MATRIX_OFFLINE=1 则禁止联网：取不到的快照整格 SKIP（打印原因）；
  - 版本集合用 KEEL_MATRIX_VERSIONS 配置（逗号分隔，current 表示当前模板）。
边角：
  - 取不到历史版本 → 该格 SKIP 并计入「未验证」，**不是 PASS**，CI 不因此变红；
  - 本机没有 python3 → 入口脚本直接 exit 2（跳过，不算失败）；
  - 不需要 Docker（矩阵只跑 bash 升级引擎）。
"""

import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import warnings
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def _find_keel(d):
    """向上找到含 keel-version 的 INDEX.md（本文件可能放在 checks/ 子目录）。"""
    while True:
        idx = os.path.join(d, "INDEX.md")
        if os.path.isfile(idx):
            with open(idx, encoding="utf-8") as fh:
                if "keel-version:" in fh.read(200):
                    return d
        p = os.path.dirname(d)
        if p == d:
            raise SystemExit("找不到 keel 目录（本文件必须位于 keel/ 之下）")
        d = p


KEEL = _find_keel(HERE)
BASH = shutil.which("bash") or "bash"
ANCHOR = "任何任务开始前，先读 keel/INDEX.md 与其中指向的 NOW.md，并遵守 INDEX.md 里的检索协议。"

DEFAULT_VERSIONS = "3.6.1,3.7.4,3.8.0,3.9.0,current"
INSTALL_CELL = "3.4.11"
CACHE = os.environ.get("KEEL_MATRIX_CACHE") or os.path.join(tempfile.gettempdir(), "keel-matrix-cache")
OFFLINE = os.environ.get("KEEL_MATRIX_OFFLINE") == "1"


def read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)


def _shipable(keel_dir):
    try:
        return "../" not in read(os.path.join(keel_dir, "INDEX.md"))
    except OSError:
        return False


if not _shipable(KEEL):
    _sibling = os.path.normpath(os.path.join(KEEL, "..", "keel-starter", "keel"))
    if _shipable(_sibling):
        print("· 本 keel/ 是规格仓实例，改用它同级的发布模板: %s" % _sibling)
        KEEL = _sibling
REPO = os.path.dirname(KEEL)


def version_of(keel_dir):
    for line in read(os.path.join(keel_dir, "INDEX.md")).splitlines():
        if line.startswith("keel-version:"):
            return line.split(":", 1)[1].strip()
    return ""


def cur_version():
    return version_of(KEEL)


def sha(p):
    with open(p, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def tree_sig(keel_dir):
    sig = {}
    for dp, _, fs in os.walk(keel_dir):
        for f in fs:
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, keel_dir)
            sig[rel] = (sha(p), os.stat(p).st_mode & 0o777)
    return sig


class Skip(Exception):
    pass


def repotag_ok():
    if not os.path.isdir(os.path.join(REPO, ".git")):
        return False
    p = subprocess.run(["git", "-C", REPO, "rev-parse", "--git-dir"],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return p.returncode == 0


def snapshot(ver):
    """按 tag 取历史模板快照（带缓存）。取不到 → Skip，绝不静默当 PASS。"""
    if ver == "current":
        return REPO
    tag = "v" + ver
    dst = os.path.join(CACHE, tag)
    if os.path.isdir(os.path.join(dst, "keel")):
        got = version_of(os.path.join(dst, "keel"))
        if got != ver:
            raise Skip("缓存损坏：%s 的 keel-version=%s" % (dst, got or "<空>"))
        return dst
    if not repotag_ok():
        raise Skip("拿不到 %s 快照：%s 不是 git 仓库（设 KEEL_MATRIX_OFFLINE=1 时同样跳过）" % (tag, REPO))
    p = subprocess.run(["git", "-C", REPO, "-c", "tar.umask=0022", "archive", "--format=tar", tag],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        if OFFLINE:
            raise Skip("拿不到 %s 快照：本地无此 tag，且 KEEL_MATRIX_OFFLINE=1 禁止联网" % tag)
        subprocess.run(["git", "-C", REPO, "fetch", "--depth", "1", "origin", tag],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        p = subprocess.run(["git", "-C", REPO, "-c", "tar.umask=0022", "archive", "--format=tar", tag],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        raise Skip("拿不到 %s 快照：git archive 失败（%s）" % (tag, p.stderr.decode("utf-8", "replace").strip()[:80]))
    os.makedirs(CACHE, exist_ok=True)
    tmp = dst + ".tmp-%d" % os.getpid()
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    with tarfile.open(fileobj=__import__("io").BytesIO(p.stdout)) as tf:
        tf.extractall(tmp)
    if version_of(os.path.join(tmp, "keel")) != ver:
        shutil.rmtree(tmp, ignore_errors=True)
        raise Skip("快照版本不符：%s 解得 %s" % (tag, version_of(os.path.join(tmp, "keel"))))
    shutil.rmtree(dst, ignore_errors=True)
    os.rename(tmp, dst)
    return dst


def run(args, cwd, env=None):
    e = dict(os.environ)
    e.pop("KEEL_UPGRADE_BOOTSTRAPPED", None)
    if env:
        e.update(env)
    p = subprocess.run(args, cwd=cwd, env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return p.returncode, p.stdout.decode("utf-8", "replace")


def build(root, snap, suffix="proj"):
    """用快照建采用方仓库：模板副本 + 点火锚点 + 自定义文件。"""
    tgt = os.path.join(root, suffix)
    os.makedirs(tgt)
    shutil.copytree(os.path.join(snap, "keel"), os.path.join(tgt, "keel"))
    write(os.path.join(tgt, "AGENTS.md"), "# matrix\n" + ANCHOR + "\n")
    now = os.path.join(tgt, "keel/NOW.md")
    write(now, read(now) + "\n## 采用方自定义\n- 矩阵用例的私有进度（不得被升级覆盖）\n")
    mine = os.path.join(tgt, "keel/decisions/0099-adopter-note.txt")
    write(mine, "采用方自建决策（非 md：不进热区，不参与孤儿/陈旧判定）\n")
    return tgt


def custom_hashes(tgt):
    return {rel: sha(os.path.join(tgt, "keel", rel))
            for rel in ("NOW.md", "decisions/0099-adopter-note.txt")
            if os.path.isfile(os.path.join(tgt, "keel", rel))}


def engine_of(tgt):
    return os.path.join(tgt, "keel/checks/keel-upgrade.sh")


def engine_caps(eng):
    """起点引擎支持哪些能力。3.6.x 早于 v3.7.1 的 pending/故障钩子。

    为什么要探测而不是一刀切：3.6.1 的引擎根本没有 `--resume`/`TEST_HOOKS`，
    拿新判据去要求它，红的是「历史版本不具备这个能力」而不是「本次升级被误判」。
    但不代表 ⑥⑦ 可以不验——采用方真实路径是 install.sh 引导，由**目标版本新引擎**
    执行，所以对能力不足的格改用引导路径验证续跑/回滚（见 legacy_resume_rollback）。
    """
    txt = read(eng)
    return {
        "hooks": "KEEL_UPGRADE_TEST_HOOKS" in txt,
        "pending": ".keel-upgrade.pending" in txt,
        "rollback": "--rollback" in txt,
    }


def legacy_resume_rollback(root, snap, src_ver, tpl):
    """起点引擎没有 pending/故障钩子时，走 install.sh 引导（新引擎）验 ⑥⑦。"""
    notes = ["起点引擎早于 v3.7.1（无 pending/故障钩子）→ 改走 install.sh 引导路径验续跑/回滚"]
    repo = make_matrix_repo(root, snap, src_ver)
    tgt = os.path.join(root, "bootstrap")
    os.makedirs(tgt)
    inst = os.path.join(KEEL, "checks/install.sh")
    env = {"KEEL_INSTALL_REPO": repo}
    rc, out = run([BASH, inst, tgt, "--ref", "v" + src_ver, "--with-anchor"], root, env=env)
    if rc != 0:
        raise AssertionError("引导前初次安装失败 rc=%d: %s"
                             % (rc, out.strip().splitlines()[-1] if out.strip() else ""))
    if version_of(os.path.join(tgt, "keel")) != src_ver:
        raise AssertionError("初次安装版本不是 %s" % src_ver)
    write(os.path.join(tgt, "keel/NOW.md"),
          read(os.path.join(tgt, "keel/NOW.md")) + "\n## 采用方自定义\n- 3.6.x 引导用例\n")
    write(os.path.join(tgt, "keel/decisions/0099-adopter-note.txt"), "# 自建\n")
    custom = custom_hashes(tgt)
    pre = tree_sig(os.path.join(tgt, "keel"))

    # 引导中断：新引擎在 backup 后被杀 → pending stage=backup
    env2 = dict(env, KEEL_UPGRADE_TEST_HOOKS="1", KEEL_UPGRADE_FAULT="after:backup")
    rc, out = run([BASH, inst, tgt], root, env=env2)
    pend = os.path.join(tgt, ".keel-upgrade.pending")
    if rc == 0 or not os.path.isfile(pend) or "stage=backup" not in read(pend):
        raise AssertionError("引导路径的 backup 中断未命中（rc=%d）" % rc)
    # 恢复入口是「重跑 install.sh」：盘上仍是旧引擎，它没有 --resume；
    # install.sh 必须把断点交给目标版本引擎接手（本轮修的就是这条）。
    rc, out = run([BASH, inst, tgt], root, env=env)
    if rc != 0:
        raise AssertionError("引导路径重跑 install.sh 未续完 rc=%d: %s"
                             % (rc, out.strip().splitlines()[-1] if out.strip() else ""))
    if os.path.exists(os.path.join(tgt, ".keel-upgrade.pending")):
        raise AssertionError("引导续跑后 pending 未清除")
    bad = check_kernel_bytes(tgt, tpl)
    if bad:
        raise AssertionError("引导续跑结果与目标模板不一致: " + "; ".join(bad[:3]))
    for k, h in custom.items():
        if sha(os.path.join(tgt, "keel", k)) != h:
            raise AssertionError("引导续跑改动了采用方自定义文件: " + k)
    notes.append("续跑：install.sh 引导中断 → 新引擎 --resume，逐字节一致")
    rc, out = run([BASH, engine_of(tgt), "--target", tgt, "--rollback"], tgt)
    if rc != 0 or tree_sig(os.path.join(tgt, "keel")) != pre:
        raise AssertionError("引导路径回滚失败 rc=%d" % rc)
    notes.append("回滚：引导后 --rollback 恢复 %s 与升级前字节/权限" % src_ver)
    return notes


def manifest_rows(keel_dir, cat):
    rows = []
    for line in read(os.path.join(keel_dir, "checks/manifest.tsv")).splitlines():
        if not line or line.startswith("#"):
            continue
        f = line.split("\t")
        if f[0] == cat:
            rows.append((f[1], f[2]))
    return rows


def check_kernel_bytes(tgt, tpl):
    bad = []
    for rel, mode in manifest_rows(tpl, "kernel"):
        a = os.path.join(tgt, "keel", rel)
        b = os.path.join(tpl, rel)
        if not os.path.isfile(a):
            bad.append("缺 " + rel)
        elif sha(a) != sha(b):
            bad.append("内容不一致 " + rel)
        elif mode and ("%o" % (os.stat(a).st_mode & 0o777)) != mode:
            bad.append("权限 %s: %s≠%s" % (rel, "%o" % (os.stat(a).st_mode & 0o777), mode))
    return bad


def check_final_state(tgt, src_ver, tpl):
    """终态五项；返回问题列表。"""
    bad = []
    if version_of(os.path.join(tgt, "keel")) != version_of(tpl):
        bad.append("版本不是目标值")
    if os.path.exists(os.path.join(tgt, ".keel-upgrade.pending")):
        bad.append("pending 未清除")
    if os.path.exists(os.path.join(tgt, ".keel-bootstrap.pending")):
        bad.append("引导标记未清除")
    left = [f for f in os.listdir(os.path.join(tgt, "keel"))
            if ".keel-new." in f]
    if left:
        bad.append("残留临时文件 " + ",".join(left))
    bks = [d for d in os.listdir(os.path.join(tgt, ".keel-backup"))
            if os.path.isdir(os.path.join(tgt, ".keel-backup", d))] if os.path.isdir(os.path.join(tgt, ".keel-backup")) else []
    ok_bk = False
    for d in bks:
        p = os.path.join(tgt, ".keel-backup", d, "keel/INDEX.md")
        if os.path.isfile(p) and version_of(os.path.dirname(p)) == src_ver:
            ok_bk = True
    if not ok_bk:
        bad.append("备份不可回滚（找不到版本 %s 的备份树）" % src_ver)
    rc, _ = run([BASH, engine_of(tgt), "--check-manifest", os.path.join(tgt, "keel")], tgt)
    if rc != 0:
        bad.append("manifest 与磁盘不一致")
    return bad


def check_lint(tgt):
    rc, out = run([BASH, "keel/checks/keel-lint.sh", "keel"], tgt)
    return rc == 0, out


def cell(ver, root, verbose=False):
    """跑一格；返回 (状态, 明细列表)。状态 ∈ PASS/FAIL/SKIP。"""
    notes = []
    t0 = time.time()
    try:
        snap = snapshot(ver)
    except Skip as e:
        return "SKIP", [str(e), "耗时 %.1fs" % (time.time() - t0)]
    src_ver = version_of(os.path.join(snap, "keel"))
    tpl = KEEL
    cur = cur_version()
    notes.append("起点 %s → 目标 %s" % (src_ver, cur))
    tgt = build(root, snap, "proj")
    pre = tree_sig(os.path.join(tgt, "keel"))
    custom = custom_hashes(tgt)
    eng = engine_of(tgt)
    if not os.path.isfile(eng):
        return "FAIL", ["起点没有升级引擎，却出现在引擎矩阵里（应走 install 用例）"]
    # ≤3.9.x 的引擎用裸 cp 覆盖目标文件，包括**正在执行的自己**：cp 走 truncate 而非
    # rename，运行中的 bash 会从同一 inode 的新内容中间继续读，实测 3.7.4 在收尾时
    # 崩在 "line 550: _rel: unbound variable"。这是旧实现的自替换缺陷，不是判据
    # 兼容性问题；把它隔离（复制到临时位置执行）才能验证矩阵真正要断言的东西。
    # 采用方的真实路径是 install.sh / 新版引擎（v3.10.0 起交接与 atomic rename 都已覆盖）。
    run_eng = eng
    if src_ver != cur:
        run_eng = os.path.join(root, "old-engine.sh")
        shutil.copy2(eng, run_eng)
    rc, out = run([BASH, run_eng, "--target", tgt, "--from", tpl, "--skip-test-lint"], tgt)
    if rc != 0:
        tail = out.strip().splitlines()[-4:] if out.strip() else []
        return "FAIL", ["升级失败 rc=%d（旧引擎 + 新模板）" % rc] + tail
    if "升级完成" not in out and cur != src_ver:
        return "FAIL", ["没有打印「升级完成」"]
    bad = check_kernel_bytes(tgt, tpl)
    bad += ["自定义被改: " + k for k, h in custom.items() if sha(os.path.join(tgt, "keel", k)) != h]
    ok, lout = check_lint(tgt)
    if not ok:
        bad.append("升级后 lint 未通过")
    upgraded = tree_sig(os.path.join(tgt, "keel"))

    if src_ver == cur:
        # 幂等：第二次执行不得新增备份或改动文件
        bkd = os.path.join(tgt, ".keel-backup")
        n1 = len([d for d in os.listdir(bkd) if os.path.isdir(os.path.join(bkd, d))]) if os.path.isdir(bkd) else 0
        rc2, out2 = run([BASH, eng, "--target", tgt, "--from", tpl, "--skip-test-lint"], tgt)
        n2 = len([d for d in os.listdir(bkd) if os.path.isdir(os.path.join(bkd, d))]) if os.path.isdir(bkd) else 0
        if rc2 != 0 or "无需升级" not in out2 or n1 != n2 or tree_sig(os.path.join(tgt, "keel")) != upgraded:
            bad.append("幂等失败 rc=%d 备份 %d→%d" % (rc2, n1, n2))
        if bad:
            return "FAIL", bad
        notes.append("幂等：无需升级、零改动、无新备份")
        notes.append("续跑/回滚：N/A（没有实际升级）")
        notes.append("耗时 %.1fs" % (time.time() - t0))
        return "PASS", notes

    bad += check_final_state(tgt, src_ver, tpl)
    if bad:
        return "FAIL", bad + [out.strip().splitlines()[-1] if out.strip() else ""]

    caps = engine_caps(run_eng)
    if not (caps["hooks"] and caps["pending"]):
        # 起点引擎没有断点语义（3.6.x）：用采用方真实路径（install.sh 引导）验 ⑥⑦
        try:
            notes += legacy_resume_rollback(root, snap, src_ver, tpl)
        except AssertionError as e:
            return "FAIL", [str(e)]
    else:
        # ⑥ 可续跑：同一快照另建一份，backup 后中断，再 --resume
        tgt2 = build(root, snap, "resume")
        run_eng2 = os.path.join(root, "old-engine-resume.sh")
        shutil.copy2(engine_of(tgt2), run_eng2)
        rc3, out3 = run([BASH, run_eng2, "--target", tgt2, "--from", tpl, "--skip-test-lint"],
                        tgt2, env={"KEEL_UPGRADE_TEST_HOOKS": "1", "KEEL_UPGRADE_FAULT": "after:backup"})
        pend = os.path.join(tgt2, ".keel-upgrade.pending")
        if rc3 == 0 or not os.path.isfile(pend) or "stage=backup" not in read(pend):
            return "FAIL", ["中断未命中 backup 阶段（rc=%d）" % rc3]
        rc4, out4 = run([BASH, run_eng2, "--target", tgt2, "--from", tpl,
                         "--skip-test-lint", "--resume"], tgt2)
        if rc4 != 0:
            return "FAIL", ["--resume 失败 rc=%d: %s" % (rc4, out4.strip().splitlines()[-1])]
        if tree_sig(os.path.join(tgt2, "keel")) != upgraded:
            return "FAIL", ["续跑结果与一次成功升级不一致"]
        notes.append("续跑：backup 中断 → --resume，逐字节一致")

        # ⑦ 可回滚：回到起点版本与升级前字节/权限
        rc5, out5 = run([BASH, engine_of(tgt), "--target", tgt, "--rollback"], tgt)
        if rc5 != 0 or tree_sig(os.path.join(tgt, "keel")) != pre:
            return "FAIL", ["回滚失败 rc=%d" % rc5]
        notes.append("回滚：恢复 %s 与升级前字节/权限" % src_ver)
    notes.append("耗时 %.1fs" % (time.time() - t0))
    return "PASS", notes


def _git(repo, *args):
    return subprocess.run(["git", "-C", repo, "-c", "user.name=matrix",
                           "-c", "user.email=matrix@example.invalid", *args],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def make_matrix_repo(root, old_snap, ver=INSTALL_CELL):
    """造一个本地发布仓：tag v<ver> = 历史快照，main = 当前工作树。

    为什么不用发布仓本身：矩阵必须在**发布前**就能跑（工作树尚未 commit），
    否则「当前版本」只能是上一个 tag，测不到本轮改动。本地仓同时避免联网。
    """
    repo = os.path.join(root, "repo")
    shutil.copytree(old_snap, repo)
    _git(repo, "init", "-q")
    subprocess.run(["git", "-C", repo, "symbolic-ref", "HEAD", "refs/heads/main"],
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "old snapshot " + ver)
    _git(repo, "tag", "v" + ver)
    for e in os.listdir(repo):
        if e == ".git":
            continue
        p = os.path.join(repo, e)
        shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
    for e in os.listdir(REPO):
        if e == ".git":
            continue
        src, dst = os.path.join(REPO, e), os.path.join(repo, e)
        shutil.copytree(src, dst) if os.path.isdir(src) else shutil.copy2(src, dst)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "current work tree")
    return repo


def install_cell(root):
    """≤3.5.0 没有升级引擎：只能重跑 install.sh 引导。验证引导真的把目标升上去。"""
    t0 = time.time()
    try:
        snap = snapshot(INSTALL_CELL)
    except Skip as e:
        return "SKIP", [str(e), "耗时 %.1fs" % (time.time() - t0)]
    cur = cur_version()
    tgt = os.path.join(root, "install")
    os.makedirs(tgt)
    inst = os.path.join(KEEL, "checks/install.sh")
    env = {"KEEL_INSTALL_REPO": make_matrix_repo(root, snap)}
    rc, out = run([BASH, inst, tgt, "--ref", "v" + INSTALL_CELL, "--with-anchor"], root, env=env)
    if rc != 0:
        return "FAIL", ["v%s 初次安装失败 rc=%d: %s" % (INSTALL_CELL, rc, out.strip().splitlines()[-1])]
    if version_of(os.path.join(tgt, "keel")) != INSTALL_CELL:
        return "FAIL", ["初次安装版本不对: " + version_of(os.path.join(tgt, "keel"))]
    now = os.path.join(tgt, "keel/NOW.md")
    write(now, read(now) + "\n## 采用方自定义\n- install 引导用例的自定义\n")
    mine = os.path.join(tgt, "keel/decisions/0099-adopter-note.txt")
    write(mine, "# 自建\n")
    custom = custom_hashes(tgt)
    rc, out = run([BASH, inst, tgt], root, env=env)
    if rc != 0:
        return "FAIL", ["install 引导升级失败 rc=%d" % rc] + (out.strip().splitlines()[-4:] if out.strip() else [])
    if version_of(os.path.join(tgt, "keel")) != cur:
        return "FAIL", ["引导后版本不是 %s" % cur]
    bad = check_kernel_bytes(tgt, KEEL)
    bad += ["自定义被改: " + k for k, h in custom.items() if sha(os.path.join(tgt, "keel", k)) != h]
    bad += check_final_state(tgt, INSTALL_CELL, KEEL)
    if os.path.exists(os.path.join(tgt, ".keel-bootstrap.pending")):
        bad.append("引导标记未清除")
    ok, _ = check_lint(tgt)
    if not ok:
        bad.append("lint 未通过")
    if bad:
        return "FAIL", bad
    return "PASS", ["%s 无引擎 → install.sh 引导 → %s，内核/自定义/终态/门禁全过" % (INSTALL_CELL, cur),
                    "耗时 %.1fs" % (time.time() - t0)]


def regression_old_backup(root):
    """REG-1：旧引擎备份没有 restore.sh —— v3.9.0 曾因此误判失败。"""
    t0 = time.time()
    tgt = build(root, REPO, "reg")
    try:
        snap = snapshot("3.8.0")
    except Skip as e:
        return "SKIP", [str(e), "耗时 %.1fs" % (time.time() - t0)]
    cur = cur_version()
    bk = os.path.join(tgt, ".keel-backup", "old-engine-layout")
    shutil.copytree(os.path.join(snap, "keel"), os.path.join(bk, "keel"))
    if os.path.exists(os.path.join(bk, "restore.sh")):
        return "FAIL", ["3.8.0 快照居然带 restore.sh，回归前提不成立"]
    # 造「升级已完成、只差清 pending」的旧引擎状态
    write(os.path.join(tgt, "keel/INDEX.md"),
          "\n".join(("keel-version: " + cur) if l.startswith("keel-version:") else l
                    for l in read(os.path.join(tgt, "keel/INDEX.md")).splitlines()) + "\n")
    write(os.path.join(tgt, ".keel-upgrade.pending"),
          "# keel-upgrade pending v1\nfrom=3.8.0\nto=%s\nstage=done\nbackup=%s\n" % (cur, bk))
    rc, out = run([BASH, engine_of(tgt), "--target", tgt, "--from", KEEL, "--resume"], tgt)
    if rc != 0:
        return "FAIL", ["旧引擎备份布局被误判失败 rc=%d（历史 bug 复发）" % rc,
                        out.strip().splitlines()[-1] if out.strip() else ""]
    if "上次升级已完成" not in out:
        return "FAIL", ["没有走到「上次升级已完成」路径"]
    if os.path.exists(os.path.join(tgt, ".keel-upgrade.pending")):
        return "FAIL", ["pending 未清除"]
    return "PASS", ["旧引擎备份无 restore.sh（3.8.0 布局）→ 终态校验通过，未误判",
                    "耗时 %.1fs" % (time.time() - t0)]


def run_tasks(tasks):
    """按 KEEL_MATRIX_JOBS 执行（默认 1=串行）。并行只改变调度，不改变任何断言。"""
    jobs = int(os.environ.get("KEEL_MATRIX_JOBS", "1") or "1")
    if jobs <= 1:
        return [t() for t in tasks]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        futs = [ex.submit(t) for t in tasks]
        return [f.result() for f in futs]


def main():
    verbose = "-v" in sys.argv or "--verbose" in sys.argv
    vers = [v.strip() for v in os.environ.get("KEEL_MATRIX_VERSIONS", DEFAULT_VERSIONS).split(",") if v.strip()]
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    root = tempfile.mkdtemp(prefix="keel-matrix-")
    print("跨版本升级矩阵 · 目标 %s · 格 %s · 缓存 %s" % (cur_version(), ",".join(vers), CACHE))
    print("=" * 78)
    # 并行前先串行预热快照缓存：解包/rename 落到同一路径，多线程同时首次取用会打架。
    # 预热只做"取快照"，不做断言；取不到的格留给 cell() 报 SKIP。
    for warm in sorted(set(vers + [INSTALL_CELL, "3.8.0"])):
        try:
            snapshot(warm)
        except Skip:
            pass
    tasks = []
    for v in vers:
        cell_root = os.path.join(root, "m-" + v.replace(".", "_"))
        os.makedirs(cell_root, exist_ok=True)
        tasks.append((lambda v=v, cell_root=cell_root: (v, cell(v, cell_root, verbose)),
                      "%s → %s" % (v, cur_version())))
    if os.environ.get("KEEL_MATRIX_NO_INSTALL_CELL") != "1":
        croot = os.path.join(root, "m-install")
        os.makedirs(croot, exist_ok=True)
        tasks.append((lambda croot=croot: (INSTALL_CELL + "(install)", install_cell(croot)),
                      "%s（install.sh 引导）" % INSTALL_CELL))
    rroot = os.path.join(root, "m-reg")
    os.makedirs(rroot, exist_ok=True)
    tasks.append((lambda rroot=rroot: ("REG-1", regression_old_backup(rroot)),
                  "REG-1 旧引擎备份布局（无 restore.sh）"))
    results = [(lbl, st, notes) for lbl, (st, notes) in run_tasks([t[0] for t in tasks])]
    for (label, st, notes), (_, heading) in zip(results, tasks):
        print("[%s] %s" % (st, heading))
        for n in notes:
            print("       " + n)

    passed = [r for r in results if r[1] == "PASS"]
    failed = [r for r in results if r[1] == "FAIL"]
    skipped = [r for r in results if r[1] == "SKIP"]
    print("=" * 78)
    print("%s：%d 通过 / %d 失败 / %d 跳过（未验证）"
          % ("✅ 矩阵通过" if not failed else "❌ 矩阵失败",
             len(passed), len(failed), len(skipped)))
    for v, _, notes in skipped:
        print("   ⚠️ 未验证：%s —— %s" % (v, notes[0] if notes else ""))
    if failed:
        for v, _, notes in failed:
            print("   ❌ %s：%s" % (v, "；".join(notes[:2])))
    if verbose:
        print("   （临时目录 %s）" % root)
    else:
        shutil.rmtree(root, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
