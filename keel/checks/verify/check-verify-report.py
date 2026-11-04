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

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

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


REQUIRED_SHAS = ["checks/keel-lint.sh", "checks/test-lint.py",
                 "checks/verify/checks-ledger.py", "checks/verify/verify.py"]


def _git(repo, *args):
    try:
        p = subprocess.run(["git", "-C", repo] + list(args), stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL)
        if p.returncode == 0:
            return p.stdout.decode("utf-8", "replace").strip()
    except OSError:
        pass
    return ""


def _sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _provenance_problems(prov, repo=None):
    """清单绑定校验（v3.14.0）。

    只证明「清单与代码自洽」：commit 是哪个、工作区是否脏、四个判据文件
    的 sha256 是否还是清单里那份。**不是防篡改**——任何人都能伪造一份自洽的
    清单；没有外部核对时它不上升为「可信」。
    """
    if not isinstance(prov, dict):
        return ["清单缺少 provenance 小节（commit / dirty / 判据文件 sha256）"]
    problems = []
    for k in ("commit", "dirty", "dirty_files", "checks_sha256",
              "platform", "locale", "generated_at"):
        if k not in prov:
            problems.append("provenance 缺字段 %s" % k)
    shas = prov.get("checks_sha256") or {}
    missing = [r for r in REQUIRED_SHAS if r not in shas]
    if missing:
        problems.append("provenance 少记录判据文件：%s" % "、".join(missing))
    if not prov.get("commit"):
        problems.append("provenance.commit 为空（生成清单时不在 git 仓库里？）")
    dirty_flag = prov.get("dirty")
    dirty_n = int(prov.get("dirty_files") or 0)
    if dirty_flag is False and dirty_n > 0:
        problems.append("provenance 自称干净但 dirty_files=%d" % dirty_n)
    if dirty_flag is True and dirty_n == 0:
        problems.append("provenance 自称 dirty 但 dirty_files=0")
    if repo:
        head = _git(repo, "rev-parse", "HEAD")
        if not head:
            problems.append("--repo 不是 git 仓库：%s" % repo)
        elif prov.get("commit") != head:
            problems.append("清单 commit=%s 与仓库 HEAD=%s 不一致（旧清单冒充新证据）"
                            % (str(prov.get("commit"))[:12], head[:12]))
        actual = [x for x in _git(repo, "status", "--porcelain").splitlines() if x]
        if dirty_flag is False and actual:
            problems.append("清单自称干净，仓库实际有 %d 个未提交文件" % len(actual))
        if dirty_n != len(actual):
            problems.append("清单 dirty_files=%d，仓库实际 %d 个未提交文件"
                            % (dirty_n, len(actual)))
        for rel in REQUIRED_SHAS:
            want = shas.get(rel)
            # provenance 里的键相对 `keel/`，仓库根的布局是 `<repo>/keel/checks/…`；
            # 也允许把 keel 目录本身当作 --repo（判据自检用的就是这种扁平 fixture）。
            path = os.path.join(repo, "keel", rel)
            if not os.path.isfile(path):
                path = os.path.join(repo, rel)
            if not os.path.isfile(path):
                problems.append("被检判据文件不存在：%s" % rel)
            elif want and _sha(path) != want:
                problems.append("%s 的 sha256 与清单不符（文件已改，清单已过期）" % rel)
    return problems


def _ledger_problems(ledger):
    """校验判据覆盖率账本的内部自洽（分子/分母/三档必须能对上）。"""
    if not isinstance(ledger, dict):
        return ["清单缺少 checks_ledger 小节（判据覆盖率账本）"]
    checks = ledger.get("checks")
    totals = ledger.get("totals") or {}
    if not isinstance(checks, list) or not checks:
        return ["checks_ledger.checks 为空或不是数组"]
    problems = []
    ids = [c.get("id") for c in checks]
    if len(set(ids)) != len(ids):
        problems.append("checks_ledger 判据编号重复")
    n = totals.get("numbered")
    if n != len(checks):
        problems.append("checks_ledger.numbered=%s 与判据条数=%d 不一致" % (n, len(checks)))
    neg = totals.get("negative")
    pos = totals.get("positive_only")
    none = totals.get("none")
    if None in (neg, pos, none):
        problems.append("checks_ledger.totals 缺 negative/positive_only/none")
    elif neg + pos + none != n:
        problems.append("checks_ledger 三档之和 %d+%d+%d != %s" % (neg, pos, none, n))
    recount = {"negative": 0, "positive_only": 0, "none": 0}
    for c in checks:
        cov = c.get("coverage")
        cases = c.get("cases") or 0
        negc = c.get("negative_cases") or 0
        if cov not in recount:
            problems.append("checks_ledger 非法 coverage=%s（%s）" % (cov, c.get("id")))
            continue
        recount[cov] += 1
        if cov == "negative" and negc == 0:
            problems.append("checks_ledger %s 标 negative 但 negative_cases=0" % c.get("id"))
        if cov == "positive_only" and (negc != 0 or cases == 0):
            problems.append("checks_ledger %s 标 positive_only 但负例=%d/用例=%d"
                            % (c.get("id"), negc, cases))
        if cov == "none" and cases != 0:
            problems.append("checks_ledger %s 标 none 但有用例=%d" % (c.get("id"), cases))
    if None not in (neg, pos, none) and recount != {"negative": neg, "positive_only": pos, "none": none}:
        problems.append("checks_ledger 三档计数与判据条目不重合")
    implemented = totals.get("implemented")
    extension = totals.get("extension")
    if implemented is not None and extension is not None and implemented + extension != n:
        problems.append("checks_ledger implemented+extension != numbered")
    pct = totals.get("coverage_pct_of_numbered")
    if n and pct is not None and abs(pct - round((neg or 0) * 100.0 / n, 1)) > 0.05:
        problems.append("checks_ledger coverage_pct 与 %d/%s 不符" % (neg or 0, n))

    # v3.14.0：§9.1 之外的附加判据（元检查 / 预算真源）必须单列，且两个口径
    # 的分母都要能从条数重算——不许只报一个好看的百分比。
    extra = ledger.get("extras")
    if not isinstance(extra, list) or not extra:
        problems.append("checks_ledger 缺 extras（§9.3 附加判据：元检查 / 预算真源）")
        extra = []
    extra_counts = {"meta": 0, "aux": 0}
    for e in extra:
        kind = e.get("kind")
        if kind not in extra_counts:
            problems.append("checks_ledger 附加判据 %s 的 kind=%s 非法" % (e.get("id"), kind))
            continue
        extra_counts[kind] += 1
        if e.get("coverage") not in recount:
            problems.append("checks_ledger 附加判据 %s coverage=%s 非法"
                            % (e.get("id"), e.get("coverage")))
        negc = e.get("negative_cases") or 0
        if e.get("coverage") == "negative" and negc == 0:
            problems.append("checks_ledger %s 标 negative 但 negative_cases=0" % e.get("id"))
        if e.get("coverage") == "none" and (e.get("cases") or 0) != 0:
            problems.append("checks_ledger %s 标 none 但有用例=%s" % (e.get("id"), e.get("cases")))
    for key, part in (("with_meta", ["meta"]), ("all", ["meta", "aux"])):
        u = totals.get(key)
        if not isinstance(u, dict):
            problems.append("checks_ledger.totals 缺 %s 口径" % key)
            continue
        den = n + sum(extra_counts[k] for k in part)
        negc = (neg or 0) + sum(1 for e in extra
                                if e.get("kind") in part and e.get("coverage") == "negative")
        if u.get("denominator") != den:
            problems.append("checks_ledger.%s 分母=%s，应为 %d（%s + 附加）"
                            % (key, u.get("denominator"), den, n))
        if u.get("negative") != negc:
            problems.append("checks_ledger.%s 分子=%s，应为 %d" % (key, u.get("negative"), negc))
        if den and abs((u.get("coverage_pct") or 0) - round(negc * 100.0 / den, 1)) > 0.05:
            problems.append("checks_ledger.%s 百分比与 %d/%d 不符" % (key, negc, den))
    for e in ledger.get("errors") or []:
        problems.append("checks_ledger 自身报错：%s" % e)
    return problems


def check(report, text, version=None, repo=None):
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

    problems.extend(_ledger_problems(_get(report, "checks_ledger")))
    problems.extend(_provenance_problems(_get(report, "provenance"), repo))

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
    led = report.get("checks_ledger") or {}
    lt = led.get("totals") or {}
    if lt.get("numbered"):
        zeros = [c.get("id") for c in (led.get("checks") or []) + (led.get("extras") or [])
                 if c.get("coverage") == "none"]
        wm = lt.get("with_meta") or {}
        al = lt.get("all") or {}
        lines.append("- 判据覆盖：%d/%d（含元检查 %d/%d；仅 §9.1 %d/%d）· coverage=0: %s"
                     % (al.get("negative", lt.get("negative", 0)),
                        al.get("denominator", lt["numbered"]),
                        wm.get("negative", 0), wm.get("denominator", 0),
                        lt.get("negative", 0), lt["numbered"],
                        "、".join(zeros) or "无"))
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
            "provenance": {
                "commit": "0" * 40, "dirty": False, "dirty_files": 0,
                "checks_sha256": {r: "0" * 64 for r in REQUIRED_SHAS},
                "platform": {"system": "test", "release": "test"},
                "locale": {"LANG": "C.UTF-8"}, "generated_at": "2026-01-01T00:00:00+08:00",
            },
            "suites": suites,
            "checks_ledger": {
                "totals": {"numbered": 2, "implemented": 1, "extension": 1,
                           "negative": 1, "positive_only": 0, "none": 1,
                           "coverage_pct_of_numbered": 50.0,
                           "coverage_pct_of_implemented": 100.0,
                           "with_meta": {"denominator": 3, "negative": 1,
                                         "coverage_pct": 33.3},
                           "all": {"denominator": 3, "negative": 1,
                                   "coverage_pct": 33.3}},
                "checks": [
                    {"id": "§9.1-1", "coverage": "negative", "cases": 1, "negative_cases": 1},
                    {"id": "§9.1-15", "coverage": "none", "cases": 0, "negative_cases": 0},
                ],
                "extras": [
                    {"id": "§9.3-DOC", "kind": "meta", "coverage": "none",
                     "cases": 0, "negative_cases": 0},
                ],
                "auxiliary": [], "meta": [], "errors": [],
            },
            "summary": {"passed": 9, "failed": failed, "skipped": skipped,
                        "verified": skipped == 0 and failed == 0}}


def selftest():
    skip_report = _mk_report([("SKIP", "SKIP"), ("lint", "PASS")], 1)
    ok_report = _mk_report([("PASS", "PASS"), ("lint", "PASS")], 0)
    fake_report = _mk_report([("PASS", "PASS"), ("lint", "PASS")], 2)
    fail_report = _mk_report([("PASS", "PASS")], 0, failed=1)
    ledger_sum = _mk_report([("PASS", "PASS")], 0)
    ledger_sum["checks_ledger"]["totals"]["none"] = 0
    ledger_neg = _mk_report([("PASS", "PASS")], 0)
    ledger_neg["checks_ledger"]["checks"][0]["negative_cases"] = 0
    ledger_missing = _mk_report([("PASS", "PASS")], 0)
    ledger_missing.pop("checks_ledger")
    ledger_extra = _mk_report([("PASS", "PASS")], 0)
    ledger_extra["checks_ledger"]["totals"]["with_meta"]["denominator"] = 2
    prov_missing = _mk_report([("PASS", "PASS")], 0)
    prov_missing.pop("provenance")
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
        ("账本三档之和不等必须被抓", ledger_sum, "全部通过", False),
        ("账本标 negative 但负例为 0 必须被抓", ledger_neg, "全部通过", False),
        ("缺 checks_ledger 小节必须被抓", ledger_missing, "全部通过", False),
        ("含元检查口径的分母对不上必须被抓", ledger_extra, "全部通过", False),
        ("缺 provenance 小节必须被抓", prov_missing, "全部通过", False),
    ]

    # provenance 绑定的真判死用例：需要真 git 仓库，否则测不到 commit / dirty / sha。
    # 每条用例用独立仓库，避免「文件被改」同时污染 dirty 断言，测不准是哪条判据红。
    repo_ok = _prov_fixture()
    if repo_ok:
        prov_ok = _mk_report([("PASS", "PASS")], 0)
        prov_ok["provenance"].update(_prov_values(repo_ok))

        repo_commit = _prov_fixture()
        prov_commit = _mk_report([("PASS", "PASS")], 0)
        prov_commit["provenance"].update(_prov_values(repo_commit))
        prov_commit["provenance"]["commit"] = "f" * 40

        repo_sha = _prov_fixture()
        prov_sha = _mk_report([("PASS", "PASS")], 0)
        prov_sha["provenance"].update(_prov_values(repo_sha))
        with open(os.path.join(repo_sha, "checks", "test-lint.py"), "a", encoding="utf-8") as fh:
            fh.write("\n# 篡改\n")
        prov_sha["provenance"]["dirty"] = True
        prov_sha["provenance"]["dirty_files"] = 1

        repo_dirty = _prov_fixture(dirty=True)
        prov_dirty = _mk_report([("PASS", "PASS")], 0)
        prov_dirty["provenance"].update(_prov_values(repo_dirty))
        prov_dirty["provenance"]["dirty"] = False
        prov_dirty["provenance"]["dirty_files"] = 0

        fixtures += [
            ("provenance 与仓库 HEAD / sha256 一致必须放行", prov_ok, "全部通过", True, repo_ok),
            ("清单 commit 与仓库 HEAD 不一致必须被抓（旧清单冒充新证据）",
             prov_commit, "全部通过", False, repo_commit),
            ("清单 sha256 与文件不符必须被抓（判据被改过）",
             prov_sha, "全部通过", False, repo_sha),
            ("清单自称干净但仓库有未提交文件必须被抓",
             prov_dirty, "全部通过", False, repo_dirty),
        ]
        for d in (repo_ok, repo_commit, repo_sha, repo_dirty):
            _prov_cleanup.append(d)
    else:
        print("[SKIP] 无 git / 判据文件缺失，跳过 provenance 的 4 条判死用例（不计入分母）")

    bad = 0
    for fx in fixtures:
        name, report, claims, expect_ok = fx[:4]
        repo_arg = fx[4] if len(fx) > 4 else None
        got = check(report, claims, version="9.9.9", repo=repo_arg)
        ok = (not got) == expect_ok
        print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                             "" if ok else " → " + "；".join(got)))
        if not ok:
            bad += 1
    for d in _prov_cleanup:
        shutil.rmtree(d, ignore_errors=True)
    _prov_cleanup[:] = []
    print("%s：判据自检 %d/%d" % ("✅" if not bad else "❌", len(fixtures) - bad, len(fixtures)))
    return 1 if bad else 0


_prov_cleanup = []


HERE = os.path.dirname(os.path.abspath(__file__))
_PROV_SRC = {
    "checks/keel-lint.sh": os.path.join(os.path.dirname(HERE), "keel-lint.sh"),
    "checks/test-lint.py": os.path.join(os.path.dirname(HERE), "test-lint.py"),
    "checks/verify/checks-ledger.py": os.path.join(HERE, "checks-ledger.py"),
    "checks/verify/verify.py": os.path.join(HERE, "verify.py"),
}


def _prov_fixture(dirty=False):
    """临时 git 仓库：拷四个判据文件、提交；dirty=True 时再压一个未跟踪文件。"""
    if not shutil.which("git") or not all(os.path.isfile(p) for p in _PROV_SRC.values()):
        return None
    d = tempfile.mkdtemp(prefix="keel-prov-")
    for rel, src in _PROV_SRC.items():
        os.makedirs(os.path.join(d, os.path.dirname(rel)), exist_ok=True)
        shutil.copy(src, os.path.join(d, rel))
    for cmd in (["init", "-q"],
                ["add", "-A"],
                ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"]):
        subprocess.run(["git", "-C", d] + cmd, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
    if dirty:
        with open(os.path.join(d, "dirty.txt"), "w", encoding="utf-8") as fh:
            fh.write("x\n")
    return d


def _prov_values(repo):
    dirty = [x for x in _git(repo, "status", "--porcelain").splitlines() if x]
    return {
        "commit": _git(repo, "rev-parse", "HEAD"),
        "dirty": bool(dirty),
        "dirty_files": len(dirty),
        "checks_sha256": {rel: _sha(os.path.join(repo, rel)) for rel in REQUIRED_SHAS},
    }


def main():
    args = sys.argv[1:]
    if "--selftest" in args:
        return selftest()
    report_path = None
    claims = []
    repo = None
    show_summary = False
    i = 0
    while i < len(args):
        if args[i] == "--report" and i + 1 < len(args):
            report_path = args[i + 1]; i += 2
        elif args[i] == "--repo" and i + 1 < len(args):
            repo = args[i + 1]; i += 2
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
        problems = check(report, text, version=version, repo=repo)
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
