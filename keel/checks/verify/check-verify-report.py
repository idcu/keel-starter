#!/usr/bin/env python3
"""check-verify-report.py —— 验证清单与发行说明的一致性判据（ADR 0005）

用法：
    python3 keel/checks/verify/check-verify-report.py --report verify-report.json --claims CHANGELOG.md
    python3 keel/checks/verify/check-verify-report.py --report verify-report.json --summary
    python3 keel/checks/verify/check-verify-report.py --selftest

判据（缺一即 exit 1）：
    1. 清单内部自洽：套件 status=PASS 却记录 skipped>0 → 「伪装 PASS」，必须被抓；
       summary.skipped 必须等于各套件 skipped 之和；SKIP 必须带原因。
    2. 清单含 SKIP、失败或「未全部验证」时，发行说明**不得**出现
       「全部通过 / 全绿 / all green」这类无条件表述。
    3. 清单含 SKIP 时，发行说明必须写出「跳过（未验证）」并给出通过数，
       即「X 通过 / Y 跳过（未验证）」——只写「通过」同样算含混。
    4. 清单有 FAIL 时，发行说明不得声称「全部通过」。

为什么要它：发布说明是给人看的，最容易在「跳过 7 例」时写成「全部通过」。
把判据做成脚本后，release.sh 在推送前就能拦住这种表述；--selftest 用构造的
「含 SKIP + 全部通过」样例证明这条判据真的会红（而不是永远绿的装饰）。
"""

import json
import os
import re
import sys

FORBIDDEN = ["全部通过", "全绿", "全部绿", "全数通过", "100% 通过",
             "全部用例通过", "全部测试通过", "all green", "all tests passed",
             "everything passed"]


def _get(report, path, default=None):
    cur = report
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def scope_section(text, version):
    """只审当前版本那一节：历史节的「全部通过」不该让本轮发布变红。"""
    if not version:
        return text
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith("## ") and version in line:
            start = i
            break
    if start is None:
        return text
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    return "\n".join(lines[start:end])


def check(report, text, version=None):
    """返回问题列表；空列表 = 通过。"""
    problems = []
    suites = _get(report, "suites", []) or []
    total_skipped = _get(report, "summary.skipped")
    total_failed = _get(report, "summary.failed", 0) or 0
    if total_skipped is None:
        total_skipped = sum(int(s.get("skipped", 0) or 0) for s in suites)
    if total_skipped != sum(int(s.get("skipped", 0) or 0) for s in suites):
        problems.append("summary.skipped=%s 与套件跳过数之和=%s 不一致"
                        % (total_skipped, sum(int(s.get("skipped", 0) or 0) for s in suites)))
    for s in suites:
        if s.get("status") == "PASS" and int(s.get("skipped", 0) or 0) > 0:
            problems.append("伪装 PASS：套件 %s 标记 PASS 却记录 %s 例跳过"
                            % (s.get("name"), s.get("skipped")))
        if s.get("status") == "SKIP" and not s.get("skip_reason"):
            problems.append("套件 %s 标记 SKIP 却没有跳过原因" % s.get("name"))

    body = scope_section(text, version)
    low = body.lower()
    hits = [p for p in FORBIDDEN if (p.lower() in low if p.isascii() else p in body)]
    if (total_skipped or total_failed) and hits:
        problems.append("含 %d 跳过 / %d 失败，发行说明却出现无条件表述：%s"
                        % (total_skipped, total_failed, "、".join(hits)))
    if total_skipped and "跳过（未验证）" not in body:
        problems.append("含 %d 例跳过，发行说明未写「跳过（未验证）」" % total_skipped)
    if total_skipped and not re.search(r"\d+\s*通过", body):
        problems.append("含 %d 例跳过，发行说明未给出「X 通过 / Y 跳过」中的 X" % total_skipped)
    # 数字也要对得上：只写「跳过（未验证）」却把 Y 写成 0，仍是含混表述。
    pm = re.search(r"(\d+)\s*通过[^\n]*?(\d+)\s*跳过（未验证）", body)
    passed = _get(report, "summary.passed", 0) or 0
    if total_skipped:
        if not pm:
            problems.append("含 %d 例跳过，发行说明未给出「X 通过 / Y 跳过（未验证）」" % total_skipped)
        else:
            if int(pm.group(2)) != total_skipped:
                problems.append("发行说明称 %s 跳过，清单是 %d 跳过" % (pm.group(2), total_skipped))
            if int(pm.group(1)) != passed:
                problems.append("发行说明称 %s 通过，清单是 %d 通过" % (pm.group(1), passed))
    elif pm and int(pm.group(2)) != 0:
        problems.append("清单无跳过，发行说明却称 %s 跳过" % pm.group(2))
    if total_failed and "失败" not in body:
        problems.append("含 %d 例失败，发行说明未标注失败" % total_failed)
    return problems


def summary(report):
    env = _get(report, "environment", {}) or {}
    total = _get(report, "summary", {}) or {}
    loc = env.get("locale") or {}
    locale = loc.get("LC_ALL") or loc.get("LANG") or "未设置"
    lines = ["## 验证状况（verify-report.json）", "",
             "- 引擎：%s · 平台：%s · locale：%s" % (
                 env.get("engine_version") or "?", env.get("platform") or "?",
                 locale)]
    if env.get("container_image"):
        lines.append("- 容器镜像：%s" % env["container_image"])
    if env.get("matrix_jobs"):
        lines.append("- 矩阵并行度：%s" % env["matrix_jobs"])
    lines.append("- 结果：%d 通过 / %d 失败 / %d 跳过（未验证）"
                 % (total.get("passed", 0), total.get("failed", 0), total.get("skipped", 0)))
    lines.append("- 套件：")
    for s in _get(report, "suites", []) or []:
        extra = ""
        if s.get("status") == "SKIP" and s.get("skip_reason"):
            extra = "（%s）" % s["skip_reason"]
        lines.append("  - %s：%s（%d 通过 / %d 失败 / %d 跳过，%ss）%s"
                     % (s.get("name"), s.get("status"), s.get("passed", 0),
                        s.get("failed", 0), s.get("skipped", 0),
                        s.get("duration_s", "?"), extra))
    cells = _get(report, "matrix_cells", []) or []
    if cells:
        lines.append("- 矩阵格：" + "；".join("%s %s" % (c["cell"], c["status"]) for c in cells))
    return "\n".join(lines)


def _mk_report(statuses, skipped, failed=0):
    suites = []
    for name, st in statuses:
        s = {"name": name, "status": st, "skip_reason": None,
             "passed": 0, "failed": 0, "skipped": 0, "cases": 0, "duration_s": 0.1}
        if st == "SKIP":
            s["skip_reason"] = "测试样本跳过原因"
        suites.append(s)
    suites[0]["skipped"] = skipped
    return {"schema": 1, "environment": {"engine_version": "9.9.9", "platform": "test"},
            "suites": suites,
            "summary": {"passed": 9, "failed": failed, "skipped": skipped,
                        "verified": skipped == 0 and failed == 0}}


def selftest():
    skip_report = _mk_report([("SKIP", "SKIP"), ("lint", "PASS")], 1)
    ok_report = _mk_report([("PASS", "PASS"), ("lint", "PASS")], 0)
    fake_report = _mk_report([("PASS", "PASS"), ("lint", "PASS")], 2)
    fail_report = _mk_report([("PASS", "PASS")], 0, failed=1)
    fixtures = [
        ("含 SKIP + 「全部通过」必须被抓", skip_report, "全部通过", False),
        ("含 SKIP + 「全部通过」英文变体必须被抓", skip_report, "All green", False),
        ("含 SKIP + 「X 通过 / Y 跳过（未验证）」必须放行", skip_report,
         "9 通过 / 1 跳过（未验证）", True),
        ("无 SKIP + 「全部通过」允许", ok_report, "全部通过", True),
        ("伪装 PASS：status=PASS 却 skipped=2 必须被抓", fake_report,
         "9 通过 / 2 跳过（未验证）", False),
        ("含 SKIP 但只写「通过」不写未验证必须被抓", skip_report,
         "9 通过", False),
        ("含 SKIP 却把跳过数写成 0 必须被抓", skip_report,
         "9 通过 / 0 跳过（未验证）", False),
        ("有 FAIL 却写「全部通过」必须被抓", fail_report, "全部通过", False),
    ]
    bad = 0
    for name, report, claims, expect_ok in fixtures:
        got = check(report, claims, version="9.9.9")
        ok = (not got) == expect_ok
        print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                             "" if ok else " → " + "；".join(got)))
        if not ok:
            bad += 1
    print("%s：判据自检 %d/%d" % ("✅" if not bad else "❌", len(fixtures) - bad, len(fixtures)))
    return 1 if bad else 0


def main():
    args = sys.argv[1:]
    if "--selftest" in args:
        return selftest()
    report_path = None
    claims = []
    show_summary = False
    i = 0
    while i < len(args):
        if args[i] == "--report" and i + 1 < len(args):
            report_path = args[i + 1]; i += 2
        elif args[i] == "--claims" and i + 1 < len(args):
            claims.append(args[i + 1]); i += 2
        elif args[i] == "--summary":
            show_summary = True; i += 1
        elif args[i] in ("-h", "--help"):
            print(__doc__); return 0
        else:
            print("❌ 未知参数: %s" % args[i]); return 2
    if not report_path:
        print("❌ 需要 --report <verify-report.json>（或 --selftest）"); return 2
    with open(report_path, encoding="utf-8") as fh:
        report = json.load(fh)
    version = (_get(report, "environment.engine_version") or "")
    rc = 0
    if show_summary or not claims:
        print(summary(report))
    for path in claims:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        problems = check(report, text, version=version)
        if problems:
            rc = 1
            print("❌ %s 与验证清单不一致：" % path)
            for p in problems:
                print("   - " + p)
        else:
            print("✅ %s 与验证清单一致" % path)
    return rc


if __name__ == "__main__":
    sys.exit(main())
