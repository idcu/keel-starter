#!/usr/bin/env python3
"""keel-upgrade 真实故障自测（Docker；DESIGN.md §12.3）

用法：
    python3 keel/checks/test-faults.py

做什么：不再用 KEEL_UPGRADE_FAULT 模拟中断，而是制造**真实故障**：
    A. 磁盘满（tmpfs 小容量）：备份阶段写满、apply 阶段写满各一条判死用例——
       要求 pending 不被写坏、错误信息可读、腾出空间后 --resume 能续完，
       且续完的树与全新安装逐字节一致。
    B. 断网（--network none）：默认在线取模板必须失败得明确、零残留；
       同一环境下 --from 离线升级必须成功。

为什么需要它：v3.7.x 的故障注入只证明"进程被杀后能续跑"。磁盘满时
`cp` / `sed` 失败而退出码没人看，会留下截断文件并把**残片哈希**记进 pending——
断点恢复会跳过真正没写完的文件，这类坏法用 SIGKILL 永远模拟不出来。

依赖：Docker（linux 容器）+ 本机 python3。没有 Docker 或设 KEEL_SKIP_DOCKER=1
时**跳过并 exit 0**（本地不出假红；CI 按同一规则跳过，需要真跑就装 Docker）。
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
KEEL = os.path.dirname(HERE)
IMAGE = os.environ.get("KEEL_FAULT_IMAGE", "python:3.11")

ANCHOR = "任何任务开始前，先读 keel/INDEX.md 与其中指向的 NOW.md，并遵守 INDEX.md 里的检索协议。"


def _shipable(keel_dir):
    try:
        with open(os.path.join(keel_dir, "INDEX.md"), encoding="utf-8") as fh:
            return "../" not in fh.read()
    except OSError:
        return False


# 规格仓里的 keel/ 是实例（引用 ../DESIGN.md），故障注入要用发布模板
TEMPLATE = KEEL
if not _shipable(KEEL):
    _sib = os.path.normpath(os.path.join(KEEL, "..", "keel-starter", "keel"))
    if _shipable(_sib):
        TEMPLATE = _sib
REPO = os.path.dirname(TEMPLATE)
TEMPLATE_REL = os.path.relpath(TEMPLATE, REPO)

CASES = []


def case(name, fn):
    CASES.append((name, fn))


def version_of(path):
    with open(os.path.join(path, "INDEX.md"), encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("keel-version:"):
                return line.split(":", 1)[1].strip()
    return ""


def docker_ok():
    if os.environ.get("KEEL_SKIP_DOCKER"):
        return False, "KEEL_SKIP_DOCKER=1"
    if not shutil.which("docker"):
        return False, "本机没有 docker"
    p = subprocess.run(["docker", "info", "--format", "{{.OSType}}"],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        return False, "docker daemon 不可用"
    if p.stdout.decode().strip() != "linux":
        return False, "Docker OSType=%s（需要 linux 容器）" % p.stdout.decode().strip()
    return True, "ok"


def run_container(script, target, tmpfs=None, network=None, timeout=600):
    cmd = ["docker", "run", "--rm", "-i", "--entrypoint", "bash",
           "-v", "%s:/src:ro" % REPO]
    if tmpfs:
        cmd += ["--tmpfs", "/small:size=%dm,exec" % tmpfs]
    if network:
        cmd += ["--network", network]
    cmd += [IMAGE, "-s", "--", target]
    p = subprocess.run(cmd, input=script.encode("utf-8"),
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    return p.returncode, p.stdout.decode("utf-8", "replace")


def prelude(target, tov):
    """容器内准备：把发布模板装成目标仓，并把版本降到 3.7.0 制造可升级状态。"""
    return """
set -u
SRC=/src/%s
TOV=%s
T=%s
mkdir -p "$T"
cp -a "$SRC" "$T/keel"
printf '# test\\n%s\\n' > "$T/AGENTS.md"
sed -i "s|^keel-version:.*|keel-version: 3.7.0|" "$T/keel/INDEX.md"
# 造"旧版本"缺文件的真实形状：删掉后来才有的 retrieval 与两个测试（它们要 apply 新建，
# 磁盘满才有机会在 apply 阶段而不是备份阶段爆）。回收站里的清单行保留，升级据此补齐。
rm -rf "$T/keel/checks/retrieval"
rm -f "$T/keel/checks/test-upgrade.py" "$T/keel/checks/test-lint.py"
""" % (TEMPLATE_REL, tov, target, ANCHOR)


def t_disk_backup():
    tov = version_of(TEMPLATE)
    script = prelude("/small/proj", tov) + r"""
free0=$(df -k /small | awk 'NR==2{print $4}')
bk=$(du -sk "$T/keel" | awk '{print $1}')
dd if=/dev/zero of=/small/ballast bs=1k count=$(( free0 - 32 )) 2>/dev/null
echo "tmpfs 余 ${free0}K，备份需≈${bk}K，压到只剩 32K"
out=$(bash "$T/keel/checks/keel-upgrade.sh" --target "$T" --from "$SRC" --skip-test-lint 2>&1); rc=$?
echo "RC1=$rc"
echo "$out" | tail -6
if [ "$rc" -eq 2 ] && printf '%s' "$out" | grep -q '备份失败'; then echo "PASS: 备份阶段明确失败（rc=2）"; else echo "FAIL: 备份阶段没有明确失败 rc=$rc"; fi
if [ -f "$T/.keel-upgrade.pending" ] && grep -q '^stage=preflight$' "$T/.keel-upgrade.pending"; then echo "PASS: pending 保留且 stage=preflight"; else echo "FAIL: pending 缺失或被写坏"; fi
if grep -q '^keel-version: 3.7.0$' "$T/keel/INDEX.md"; then echo "PASS: 失败路径未改动 keel 树"; else echo "FAIL: 失败路径改了 keel 树"; fi
rm -f /small/ballast
out=$(bash "$T/keel/checks/keel-upgrade.sh" --target "$T" --resume --from "$SRC" --skip-test-lint 2>&1); rc=$?
echo "RC2=$rc"
echo "$out" | tail -4
if [ "$rc" -eq 0 ] && [ ! -f "$T/.keel-upgrade.pending" ] && grep -q "^keel-version: ${TOV}$" "$T/keel/INDEX.md"; then echo "PASS: 腾出空间后 --resume 续完（${TOV}）"; else echo "FAIL: --resume 未完成 rc=$rc"; fi
( cd "$T" && bash keel/checks/keel-lint.sh keel >/tmp/lint.out 2>&1 ); echo "LINT=$?"
"""
    rc, out = run_container(script, "/small/proj", tmpfs=4)
    return rc, out


def t_disk_apply():
    tov = version_of(TEMPLATE)
    script = prelude("/small/proj", tov) + r"""
free0=$(df -k /small | awk 'NR==2{print $4}')
bk=$(du -sk "$T/keel" | awk '{print $1}')
# 留 备份 + 24K：备份能过，apply 一遇到"要新建的文件"就写满
dd if=/dev/zero of=/small/ballast bs=1k count=$(( free0 - bk - 24 )) 2>/dev/null
echo "tmpfs 余 ${free0}K，备份≈${bk}K，压到 ${bk}+24K"
out=$(bash "$T/keel/checks/keel-upgrade.sh" --target "$T" --from "$SRC" --skip-test-lint 2>&1); rc=$?
echo "RC1=$rc"
echo "$out" | tail -6
if [ "$rc" -eq 2 ] && printf '%s' "$out" | grep -q '写入失败'; then echo "PASS: apply 阶段明确失败（rc=2）"; else echo "FAIL: apply 阶段没有明确失败 rc=$rc"; fi
st=$(sed -n 's/^stage=//p' "$T/.keel-upgrade.pending" 2>/dev/null | head -1)
case "${st:-}" in backup|applying) echo "PASS: pending 完整可读（stage=$st）";; *) echo "FAIL: pending 缺失或写坏（stage=${st:-无}）";; esac
# 核心：pending 里记录的文件哈希必须与磁盘一致（记错 = 续跑会跳过没写完的文件）
awk -F'\t' '$1=="file"{print $2"\t"$3}' "$T/.keel-upgrade.pending" 2>/dev/null | while IFS=$'\t' read -r rel h; do
  got=$(sha256sum "$T/keel/$rel" 2>/dev/null | awk '{print $1}')
  [ "$got" = "$h" ] || echo "FAIL: pending 记录的哈希与磁盘不一致: $rel"
done
if find "$T/keel" -name '*.sh' -size 0 | grep -q .; then echo "FAIL: 磁盘满留下 0 字节脚本"; else echo "PASS: 无 0 字节脚本"; fi
if grep -q '^to=' "$T/.keel-upgrade.pending" && grep -q '^backup=' "$T/.keel-upgrade.pending"; then echo "PASS: pending 含 to/backup 元信息（续跑可按备份回滚）"; else echo "FAIL: pending 缺 to/backup 字段"; fi
rm -f /small/ballast
out=$(bash "$T/keel/checks/keel-upgrade.sh" --target "$T" --resume --from "$SRC" --skip-test-lint 2>&1); rc=$?
echo "RC2=$rc"
echo "$out" | tail -4
if [ "$rc" -eq 0 ] && [ ! -f "$T/.keel-upgrade.pending" ] && grep -q "^keel-version: ${TOV}$" "$T/keel/INDEX.md"; then echo "PASS: 腾出空间后 --resume 续完"; else echo "FAIL: --resume 未完成 rc=$rc"; fi
if diff -r "$SRC" "$T/keel" >/dev/null 2>&1; then echo "PASS: 续跑后的树与全新安装逐字节一致"; else echo "FAIL: 续跑后的树与全新安装不一致"; fi
( cd "$T" && bash keel/checks/keel-lint.sh keel >/tmp/lint.out 2>&1 ); echo "LINT=$?"
"""
    rc, out = run_container(script, "/small/proj", tmpfs=4)
    return rc, out


def t_offline():
    tov = version_of(TEMPLATE)
    script = prelude("/work/proj", tov) + r"""
before=$(cd "$T" && find keel -type f | sort | xargs sha256sum | sha256sum | awk '{print $1}')
out=$(bash "$T/keel/checks/keel-upgrade.sh" --target "$T" --to "v$TOV" --skip-test-lint 2>&1); rc=$?
echo "RC1=$rc"
echo "$out" | tail -5
if [ "$rc" -eq 2 ] && printf '%s' "$out" | grep -q '拉取模板失败'; then echo "PASS: 断网下在线取模板失败得明确（rc=2）"; else echo "FAIL: 断网错误不明确 rc=$rc"; fi
if [ -f "$T/.keel-upgrade.pending" ]; then echo "FAIL: 断网失败残留 pending"; else echo "PASS: 断网失败无 pending"; fi
if [ -d "$T/.keel-backup" ]; then echo "FAIL: 断网失败留下备份目录"; else echo "PASS: 断网失败无备份残留"; fi
after=$(cd "$T" && find keel -type f | sort | xargs sha256sum | sha256sum | awk '{print $1}')
if [ "$before" = "$after" ]; then echo "PASS: 断网失败未改动目标树"; else echo "FAIL: 断网失败改了目标树"; fi
out=$(bash "$T/keel/checks/keel-upgrade.sh" --target "$T" --from "$SRC" --skip-test-lint 2>&1); rc=$?
echo "RC2=$rc"
echo "$out" | tail -4
if [ "$rc" -eq 0 ] && [ ! -f "$T/.keel-upgrade.pending" ] && grep -q "^keel-version: ${TOV}$" "$T/keel/INDEX.md"; then echo "PASS: 同环境 --from 离线升级成功"; else echo "FAIL: --from 离线升级失败 rc=$rc"; fi
"""
    rc, out = run_container(script, "/work/proj", network="none")
    return rc, out


case("磁盘满：备份阶段（真实 tmpfs ENOSPC）", t_disk_backup)
case("磁盘满：apply 阶段（续跑后与全新安装逐字节一致）", t_disk_apply)
case("断网：在线取模板明确失败 / --from 离线成功", t_offline)


def summarize(out):
    """判据：容器真的跑了（出现 PASS/FAIL 标记）+ 无 FAIL + 无 LINT≠0。"""
    if "PASS:" not in out:
        return False, "容器未产生断言输出（镜像/启动失败？）"
    bad = [l for l in out.splitlines() if l.startswith("FAIL:")]
    if bad:
        return False, bad[0]
    if "LINT=0" not in out and "LINT=" in out:
        return False, "续跑后 keel-lint 未通过"
    return True, ""


def main():
    ok, why = docker_ok()
    if not ok:
        print("SKIP：%s —— 真实故障用例需要 Docker linux 容器。" % why)
        print("      跳过条件：无 docker / docker daemon 不可用 / OSType≠linux / KEEL_SKIP_DOCKER=1；")
        print("      CI 上同一条规则生效，不会因缺 Docker 变红。")
        return 0
    print("keel-upgrade 真实故障自测 · 镜像 %s · 模板 %s" % (IMAGE, TEMPLATE_REL))
    print("=" * 76)
    failed = 0
    for name, fn in CASES:
        rc, out = fn()
        ok2, msg = summarize(out)
        passed = rc == 0 and ok2
        print("[%s] %s" % ("PASS" if passed else "FAIL", name))
        if not passed:
            failed += 1
            print("    " + (msg or "docker rc=%d" % rc))
            for line in out.splitlines()[-10:]:
                print("    | " + line)
    print("=" * 76)
    print("%s：%d/%d（跳过条件见文件头；无 Docker 时本套件整体 SKIP）"
          % ("✅ 真实故障自测通过" if not failed else "❌ 真实故障自测失败",
             len(CASES) - failed, len(CASES)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
