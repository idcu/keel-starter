#!/usr/bin/env python3
"""verify.py —— 机器可读的完整验证清单（DESIGN.md §12.3 / ADR 0005）

用法：
    python3 keel/checks/verify/verify.py [--out verify-report.json] [--label 名称]
                                  [--suites lint,manifest,test-lint,test-upgrade,test-faults,matrix,claims-selftest]
                                  [--strict]

做什么：依次跑完整验证套件，把每一套的结果写成结构化清单（JSON）：
    套件名 / 结果（PASS‑FAIL‑SKIP）/ 跳过原因 / 用例数 / 通过·失败·跳过数 /
    耗时 / 环境（平台、locale、容器镜像、引擎版本）/ 覆盖到的矩阵格。

为什么要它：口头说「全绿」无法核验，而「跳过」最容易被写成「通过」。清单把
「跑了多少、跳了多少、为什么跳」变成机器可读的字段；release.sh 据此生成发行
说明，并在清单含 SKIP 时禁止出现「全部通过 / 全绿」（判据见 check-verify-report.py）。

退出码：0 = 无 FAIL（允许 SKIP，与各套件默认策略一致）；1 = 有 FAIL 或 --strict 下有 SKIP；
        2 = 用法 / 环境错误（如缺 python3，由 verify.sh 处理）。
"""

import argparse
import datetime
import json
import os
import platform as _platform
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def _find_keel(d):
    """向上找到含 keel-version 的 INDEX.md（本文件在 checks/verify/ 子目录）。"""
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


def _shipable(keel_dir):
    try:
        with open(os.path.join(keel_dir, "INDEX.md"), encoding="utf-8") as fh:
            return "../" not in fh.read()
    except OSError:
        return False


KEEL = _find_keel(HERE)
if not _shipable(KEEL):
    _sib = os.path.normpath(os.path.join(KEEL, "..", "keel-starter", "keel"))
    if _shipable(_sib):
        print("· 本 keel/ 是规格仓实例，改用同级发布模板: %s" % _sib)
        KEEL = _sib
REPO = os.path.dirname(KEEL)
BASH = shutil.which("bash") or "bash"
PY = sys.executable

ALL_SUITES = ["claims-selftest", "lint", "manifest", "test-lint",
              "test-upgrade", "test-faults", "matrix"]

SUITE_CMD = {
    "claims-selftest": [PY, "keel/checks/verify/check-verify-report.py", "--selftest"],
    "lint": [BASH, "keel/checks/keel-lint.sh", "keel"],
    "manifest": [BASH, "keel/checks/keel-upgrade.sh", "--check-manifest", "keel"],
    "test-lint": [BASH, "keel/checks/test-lint.sh"],
    "test-upgrade": [BASH, "keel/checks/test-upgrade.sh"],
    "test-faults": [PY, "keel/checks/test-faults.py"],
    "matrix": [PY, "keel/checks/matrix/test-upgrade-matrix.py"],
}


def version_of(keel_dir):
    try:
        with open(os.path.join(keel_dir, "INDEX.md"), encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("keel-version:"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return ""


def run(args, timeout=None):
    env = dict(os.environ)
    env.pop("KEEL_UPGRADE_BOOTSTRAPPED", None)
    p = subprocess.run(args, cwd=REPO, env=env, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, timeout=timeout)
    return p.returncode, p.stdout.decode("utf-8", "replace")


def _num(m):
    return int(m.group(1)) if m else 0


def parse_gate(rc, out):
    return {"passed": 1 if rc == 0 else 0, "failed": 0 if rc == 0 else 1,
            "skipped": 0, "cases": 1}


def parse_test_lint(rc, out):
    # 元检查的 SKIP（例如发布版 starter 没有 DESIGN.md）也是「未验证」，
    # 必须进清单；只打印在原始输出里、清单记 0 跳过，等于在机器可读层伪装 PASS。
    skips = [l.strip() for l in out.splitlines() if l.startswith("[SKIP]")]
    reason = "；".join(skips)
    # test-lint 的口径是「跳过计入分母、也计入 ok」（保证平台无关的 50/50 承诺），
    # 所以打印的 ok **包含**被跳过的用例。清单若照抄 ok，就会把同一个用例既记
    # passed 又记 skipped，总和比实际多 1（v3.12.0 实测：98+0+1 vs 100）。
    # 因此这里减去 skips，并对 cases 不再叠加——passed + failed + skipped == cases。
    m = re.search(r"✅ 自测通过：(\d+)/(\d+)（(\d+) 用例 \+ 2 元检查）", out)
    if m:
        ok = int(m.group(1))
        return {"passed": ok - len(skips), "failed": 0, "skipped": len(skips),
                "cases": int(m.group(3)) + 2, "reason": reason}
    m = re.search(r"❌ 自测失败：(\d+) 项未通过（共 (\d+) 项）", out)
    if m:
        bad, total = int(m.group(1)), int(m.group(2))
        return {"passed": total - bad - len(skips), "failed": bad, "skipped": len(skips),
                "cases": total, "reason": reason}
    if rc == 2:
        return {"passed": 0, "failed": 0, "skipped": 0, "cases": 0,
                "reason": out.strip().splitlines()[-1] if out.strip() else "缺 python3"}
    return {"passed": 0, "failed": 1, "skipped": 0, "cases": 0,
            "reason": "无法解析 test-lint 汇总输出"}


def parse_test_upgrade(rc, out):
    m = re.search(r"✅ 升级自测通过：(\d+)/(\d+)", out)
    if m:
        return {"passed": int(m.group(1)), "failed": 0, "skipped": 0,
                "cases": int(m.group(2))}
    m = re.search(r"❌ 升级自测失败：(\d+) 项未通过（共 (\d+) 项）", out)
    if m:
        bad, total = int(m.group(1)), int(m.group(2))
        return {"passed": total - bad, "failed": bad, "skipped": 0, "cases": total}
    if rc == 2:
        return {"passed": 0, "failed": 0, "skipped": 0, "cases": 0,
                "reason": out.strip().splitlines()[-1] if out.strip() else "缺 python3"}
    return {"passed": 0, "failed": 1, "skipped": 0, "cases": 0,
            "reason": "无法解析 test-upgrade 汇总输出"}


SUMMARY_RE = re.compile(r"：(\d+) 通过 / (\d+) 失败 / (\d+) 跳过（未验证）")


def parse_faults(rc, out):
    m = SUMMARY_RE.search(out)
    p, f, s = (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else (0, 1, 0)
    reason = ""
    for line in out.splitlines():
        if line.startswith("SKIP：") or "环境分类：" in line:
            reason += line.strip() + "；"
    return {"passed": p, "failed": f, "skipped": s, "cases": p + f + s,
            "reason": reason.rstrip("；")}


CELL_RE = re.compile(r"^\[(PASS|FAIL|SKIP)\] (.+)$", re.M)


def parse_matrix(rc, out):
    m = SUMMARY_RE.search(out)
    p, f, s = (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else (0, 1, 0)
    cells = []
    for st, rest in CELL_RE.findall(out):
        label = rest.split(" ", 1)[0].split("（", 1)[0]
        cells.append({"cell": label, "status": st})
    reason = "；".join(c["cell"] for c in cells if c["status"] == "SKIP")
    return {"passed": p, "failed": f, "skipped": s, "cases": p + f + s,
            "reason": ("矩阵格未验证: " + reason) if reason else "",
            "cells": cells}


def parse_selftest(rc, out):
    p = len(re.findall(r"^\[PASS\]", out, re.M))
    f = len(re.findall(r"^\[FAIL\]", out, re.M))
    return {"passed": p, "failed": f, "skipped": 0, "cases": p + f}


PARSERS = {
    "claims-selftest": parse_selftest,
    "lint": parse_gate,
    "manifest": parse_gate,
    "test-lint": parse_test_lint,
    "test-upgrade": parse_test_upgrade,
    "test-faults": parse_faults,
    "matrix": parse_matrix,
}


def status_of(rc, parsed):
    if rc == 2:
        return "SKIP"
    if rc != 0 or parsed["failed"]:
        return "FAIL"
    if parsed["skipped"]:
        return "SKIP"
    return "PASS"


def environment(container_image=None):
    return {
        "platform": sys.platform,
        "platform_release": _platform.release(),
        "python": _platform.python_version(),
        "locale": {k: os.environ.get(k) for k in ("LANG", "LC_ALL", "LC_CTYPE")},
        # 优先级：显式声明 > test-faults 实际打印的镜像 > 空（未用容器）
        "container_image": os.environ.get("KEEL_VERIFY_IMAGE") or container_image,
        "engine_version": version_of(KEEL),
        "matrix_jobs": os.environ.get("KEEL_MATRIX_JOBS", "1"),
    }


def main():
    ap = argparse.ArgumentParser(description="生成机器可读验证清单")
    ap.add_argument("--out", default="verify-report.json")
    ap.add_argument("--label", default="")
    ap.add_argument("--suites", default=",".join(ALL_SUITES))
    ap.add_argument("--strict", action="store_true", help="有 SKIP 时也 exit 1")
    a = ap.parse_args()
    suites = [s.strip() for s in a.suites.split(",") if s.strip()]
    bad = [s for s in suites if s not in SUITE_CMD]
    if bad:
        print("❌ 未知套件: %s（可用: %s）" % (",".join(bad), ",".join(ALL_SUITES)))
        return 2

    print("验证清单 · 引擎 %s · 目标仓 %s" % (version_of(KEEL), REPO))
    print("=" * 76)
    rows = []
    fault_image = None
    for name in suites:
        t0 = time.time()
        rc, out = run(SUITE_CMD[name])
        duration = round(time.time() - t0, 1)
        if name == "test-faults":
            m = re.search(r"镜像 (\S+)", out)
            fault_image = m.group(1) if m else None
        parsed = PARSERS[name](rc, out)
        st = status_of(rc, parsed)
        reason = parsed.get("reason") or ("" if st != "SKIP" else "%d 例未验证" % parsed["skipped"])
        row = {
            "name": name,
            "status": st,
            "skip_reason": reason or None,
            "cases": parsed["cases"],
            "passed": parsed["passed"],
            "failed": parsed["failed"],
            "skipped": parsed["skipped"],
            "duration_s": duration,
        }
        if "cells" in parsed:
            row["cells"] = parsed["cells"]
        rows.append(row)
        print("[%-4s] %-16s %d 通过 / %d 失败 / %d 跳过 · %ss%s"
              % (st, name, row["passed"], row["failed"], row["skipped"], duration,
                 (" · " + reason) if reason else ""))

    cells = [c for r in rows if "cells" in r for c in r["cells"]]
    total = {
        "passed": sum(r["passed"] for r in rows),
        "failed": sum(r["failed"] for r in rows),
        "skipped": sum(r["skipped"] for r in rows),
    }
    report = {
        "schema": 1,
        "generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "label": a.label or None,
        "environment": environment(container_image=fault_image),
        "suites": rows,
        "matrix_cells": cells,
        "summary": {
            "passed": total["passed"],
            "failed": total["failed"],
            "skipped": total["skipped"],
            "verified": total["failed"] == 0 and total["skipped"] == 0,
        },
    }
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    print("=" * 76)
    if total["failed"]:
        head = "❌ 验证失败"
    elif total["skipped"]:
        head = "⚠️ 验证未全部覆盖"
    else:
        head = "✅ 验证通过"
    print("%s：%d 通过 / %d 失败 / %d 跳过（未验证） → %s"
          % (head, total["passed"], total["failed"], total["skipped"], a.out))
    if total["skipped"]:
        print("   发行说明不得写「全部通过 / 全绿」；应为「%d 通过 / %d 跳过（未验证）」"
              % (total["passed"], total["skipped"]))
    if total["failed"] or (a.strict and total["skipped"]):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
