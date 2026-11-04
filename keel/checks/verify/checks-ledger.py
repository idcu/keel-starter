#!/usr/bin/env python3
"""checks-ledger.py —— 判据清单与覆盖率账本（《Keel 设计稿》§9.1 / §12.3）

用法：
    python3 keel/checks/verify/checks-ledger.py --summary
    python3 keel/checks/verify/checks-ledger.py --json [--out checks-ledger.json]
    python3 keel/checks/verify/checks-ledger.py --selftest
    python3 keel/checks/verify/checks-ledger.py --cases <test-lint.py> [--design DESIGN.md]

口径（必须与 DESIGN §12.3 一致）：
    分母 = §9.1 的 19 个编号。第 15 项是项目扩展位，内核不实现，记为 coverage=none。
    三档：
      negative      = 有负例（fail 级 rc=1；warn 级 rc=0 且断言了告警文本）
      positive_only = 只有合法基线（rc=0 且无期望输出）
      none          = 没有任何用例（coverage=0）

为什么分母不合成一个数：
    「18/19 = 94.7%」与「18/18 = 100%」都能被讲成好消息，
    但 §9.3 预算检查、5 个元检查、3 个动态套件都不在 19 项里。
    账本必须同时打印分母与未覆盖清单，禁止只报百分比。
"""

import argparse
import datetime
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
KEEL = os.path.dirname(os.path.dirname(HERE))
REPO = os.path.dirname(KEEL)
DEFAULT_CASES = os.path.join(KEEL, "checks", "test-lint.py")
DEFAULT_DESIGN = os.path.join(REPO, "DESIGN.md")

# 单一真源：判据编号只在这里声明一次。
# 标题来自 DESIGN §9.1；编号必须连续 1..19，缺号/重号由 --selftest 判死。
REGISTRY = [
    ("§9.1-1", "fail", "大小：行数 / 字节 / 单行字节 / 单目录文件数超限"),
    ("§9.1-2", "fail", "frontmatter：缺失、字段缺失、行数 / 字节超限"),
    ("§9.1-3", "fail", "死链：@路径 与 markdown 链接指向不存在的文件"),
    ("§9.1-4", "fail", "孤儿：热区文档未被任何热区文档以链接引用"),
    ("§9.1-5", "fail", "坑条目三段式（症状 / 根因 / 正解）缺失"),
    ("§9.1-6", "fail", "值域：status / severity / keywords / last-verified / triggers"),
    ("§9.1-7", "fail", "登记：坑未进 pitfalls/INDEX；域索引含非表格正文"),
    ("§9.1-8", "fail", "命名：热区文件名含日期 / 大写 / 下划线 / 空格"),
    ("§9.1-9", "fail", "循环引用：md → md 引用图存在环"),
    ("§9.1-10", "fail", "必读与点火：必读文件缺失、根索引缺字段、锚点不一致"),
    ("§9.1-11", "fail", "状态机：frozen 期间新增 contracts；单月例外决策 >2"),
    ("§9.1-12", "warn", "陈旧：last-verified 超 30 天；NOW 的 updated 超 7 天"),
    ("§9.1-13", "warn", "待蒸馏：triggers ≥ 3 且 status ≠ distilled"),
    ("§9.1-14", "fail", "取代关系：decisions/* 的 superseded-by 指向不存在文件"),
    ("§9.1-15", "extension", "契约漂移 / 术语混用（项目扩展位，内核不实现）"),
    ("§9.1-16", "fail", "闭环钩子本体：pre-commit / commit-msg 缺失或不可执行"),
    ("§9.1-17", "fail", "版本副本一致：keel-version / CHANGELOG / README 徽章"),
    ("§9.1-18", "fail", "跨平台底线：CRLF；仅大小写不同的路径"),
    ("§9.1-19", "fail", "写路径收敛：禁止裸 cp/mv/install、sed -i、重定向直写"),
]

META = [
    {"id": "NOISE", "counted_in_selftest_total": True,
     "note": "全部用例的 stderr 必须为空或命中显式豁免（ADR 0014）"},
    {"id": "INVOKE", "counted_in_selftest_total": True,
     "note": "lint 的入参形式无关（相对 / 绝对 / . / 带空格）"},
    {"id": "DOC", "counted_in_selftest_total": False,
     "note": "脚本与 DESIGN §9.3 逐字一致；失败会计入 bad，但不进自测总数"},
    {"id": "LOCALE", "counted_in_selftest_total": False,
     "note": "段 3 LC_ALL 不泄漏；段 4 与 locale 无关"},
    {"id": "PROSE", "counted_in_selftest_total": False,
     "note": "门面散文数字与真源一致；不进自测总数"},
]

AUX_NOTES = {
    "§9.3": "预算真源检查（有负例），不在 §9.1 编号内",
    "§3.4": "命名豁免的合法基线（支持性用例，不是独立检查项）",
    "§6.1": "frontmatter 行内注释的合法基线",
    "§9.4": "陈旧豁免的合法基线",
    "§12.1": "MVP 全绿基线",
}


def load_cases(path):
    """导入 test-lint.py，直接读 CASES —— 不解析文本、不维护第二份清单。"""
    name = "keel_cases_%s" % uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return list(mod.CASES)


def classify(case):
    rc = case[4]
    expect = case[3] or []
    if rc == 1:
        return "death"
    if rc == 0 and expect:
        return "warn"
    return "baseline"


def parse_design_91(text):
    """从 DESIGN §9.1 表提取编号；找不到小节返回 None。"""
    start = text.find("### 9.1")
    if start < 0:
        return None
    end = text.find("### 9.2", start)
    if end < 0:
        end = len(text)
    nums = []
    for line in text[start:end].splitlines():
        m = re.match(r"^\|\s*(\d+)\s*\|", line)
        if m:
            nums.append(int(m.group(1)))
    return nums


def build(cases, design_text=None):
    errors = []
    ids = [c[0] for c in REGISTRY]
    nums = []
    for cid in ids:
        m = re.match(r"§9\.1-(\d+)$", cid)
        if not m:
            errors.append("判据编号不符合 §9.1-N：%s" % cid)
            continue
        nums.append(int(m.group(1)))
    if sorted(nums) != list(range(1, 20)):
        errors.append("判据编号不连续：%s" % ",".join(map(str, nums)))
    if len(set(ids)) != len(ids):
        errors.append("判据编号重复")

    known = set(ids)
    for ref in sorted({c[2] for c in cases}):
        if re.match(r"§9\.1-\d+$", ref) and ref not in known:
            errors.append("test-lint 引用了未登记的判据：%s" % ref)

    rows = []
    for cid, level, title in REGISTRY:
        cs = [c for c in cases if c[2] == cid]
        death = sum(1 for c in cs if classify(c) == "death")
        warn = sum(1 for c in cs if classify(c) == "warn")
        base = sum(1 for c in cs if classify(c) == "baseline")
        if level == "fail":
            negative = death
        elif level == "warn":
            negative = warn
        else:
            negative = 0
        if negative:
            coverage = "negative"
        elif cs:
            coverage = "positive_only"
        else:
            coverage = "none"
        rows.append({
            "id": cid,
            "level": level,
            "kind": "extension" if level == "extension" else "rule",
            "title": title,
            "cases": len(cs),
            "negative_cases": negative,
            "death_cases": death,
            "warn_cases": warn,
            "baseline_cases": base,
            "coverage": coverage,
        })

    numbered = len(rows)
    implemented = sum(1 for r in rows if r["kind"] == "rule")
    extension = numbered - implemented
    negative = sum(1 for r in rows if r["coverage"] == "negative")
    positive_only = sum(1 for r in rows if r["coverage"] == "positive_only")
    none = sum(1 for r in rows if r["coverage"] == "none")
    neg_fail = sum(1 for r in rows if r["level"] == "fail" and r["negative_cases"] > 0)
    neg_warn = sum(1 for r in rows if r["level"] == "warn" and r["negative_cases"] > 0)
    if negative + positive_only + none != numbered:
        errors.append("三档之和 != 判据总数")

    aux = []
    for ref in sorted({c[2] for c in cases if not c[2].startswith("§9.1-")}):
        cs = [c for c in cases if c[2] == ref]
        aux.append({
            "id": ref,
            "note": AUX_NOTES.get(ref, "未登记的辅助用例引用"),
            "cases": len(cs),
            "negative_cases": sum(1 for c in cs if classify(c) in ("death", "warn")),
            "baseline_cases": sum(1 for c in cs if classify(c) == "baseline"),
        })

    design_check = {"path": None, "status": "skipped", "rows": None}
    if design_text is not None:
        design_check["status"] = "checked"
        nums_in_doc = parse_design_91(design_text)
        if nums_in_doc is None:
            errors.append("DESIGN 找不到 §9.1 小节")
        elif sorted(nums_in_doc) != list(range(1, 20)):
            errors.append("DESIGN §9.1 行数与账本不一致：doc=%d, ledger=%d（缺 %s）"
                          % (len(nums_in_doc), numbered,
                             ",".join(map(str, sorted(set(range(1, 20)) - set(nums_in_doc)))) or "无"))
        design_check["rows"] = len(nums_in_doc) if nums_in_doc else 0

    return {
        "schema": 1,
        "generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "scope": {"numbered": "§9.1-1..19", "extension_slot": "§9.1-15",
                  "excludes": ["元检查（NOISE/INVOKE/DOC/LOCALE/PROSE）",
                               "动态套件（test-upgrade/test-faults/matrix）",
                               "§9.3 预算真源检查（单列 auxiliary）"]},
        "design_check": design_check,
        "totals": {
            "numbered": numbered,
            "implemented": implemented,
            "extension": extension,
            "negative": negative,
            "negative_fail_level": neg_fail,
            "negative_warn_level": neg_warn,
            "positive_only": positive_only,
            "none": none,
            "coverage_pct_of_numbered": round(negative * 100.0 / numbered, 1),
            "coverage_pct_of_implemented": round(negative * 100.0 / implemented, 1),
        },
        "checks": rows,
        "auxiliary": aux,
        "meta": META,
        "out_of_scope": ["test-upgrade", "test-faults", "matrix"],
        "errors": errors,
    }


def summary_of(ledger):
    t = ledger["totals"]
    zeros = [r for r in ledger["checks"] if r["coverage"] == "none"]
    lines = [
        "判据覆盖：%d/%d 有负例（%d 判死 + %d 告警；%.1f%%）；按已实现判据 %d/%d（%.1f%%）"
        % (t["negative"], t["numbered"], t["negative_fail_level"],
           t["negative_warn_level"], t["coverage_pct_of_numbered"],
           t["negative"], t["implemented"], t["coverage_pct_of_implemented"]),
        "  - 负例 %d · 只有正例 %d · 无用例 %d"
        % (t["negative"], t["positive_only"], t["none"]),
    ]
    if zeros:
        lines.append("  - coverage=0：%s"
                     % "；".join("%s（%s）" % (r["id"], r["title"]) for r in zeros))
    else:
        lines.append("  - coverage=0：无")
    aux_bad = [a for a in ledger["auxiliary"] if a["negative_cases"]]
    if aux_bad:
        lines.append("  - 另列：%s"
                     % "；".join("%s %s" % (a["id"], a["note"]) for a in aux_bad))
    counted = [m for m in ledger["meta"] if m["counted_in_selftest_total"]]
    lines.append("  - 元检查 %d 个，其中 %d 个进自测分母；其余 %d 个只计入失败数"
                 % (len(ledger["meta"]), len(counted), len(ledger["meta"]) - len(counted)))
    if ledger["design_check"]["status"] == "checked":
        lines.append("  - DESIGN §9.1 对齐：%s 行" % ledger["design_check"]["rows"])
    for e in ledger["errors"]:
        lines.append("  ❌ " + e)
    return "\n".join(lines)


def _run_fixture(name, cond):
    print("[%s] %s" % ("PASS" if cond else "FAIL", name))
    return bool(cond)


def _copy_without(src, ids):
    tmp = tempfile.mkdtemp(prefix="keel-ledger-")
    dst = os.path.join(tmp, "test-lint.py")
    keep = []
    drop_prefix = tuple('@case("%s"' % i for i in ids)
    with open(src, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith(drop_prefix):
                continue
            keep.append(line)
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write("".join(keep))
    return tmp, load_cases(dst)


def _design_text(n):
    rows = ["### 9.1 判据总表", "| # | 检查 | 级别 |", "|---|---|---|"]
    for i in range(1, n + 1):
        rows.append("| %d | 示例 %d | ❌ fail |" % (i, i))
    rows.append("### 9.2 扩展检查接口")
    return "\n".join(rows)


def selftest():
    cases_path = DEFAULT_CASES
    for i, a in enumerate(sys.argv):
        if a == "--cases" and i + 1 < len(sys.argv):
            cases_path = sys.argv[i + 1]
    good = 0
    total = 0

    base = load_cases(cases_path)
    led = build(base)
    total += 1
    good += _run_fixture("真实用例：19 项、18 项有负例、1 项无",
                         led["totals"]["numbered"] == 19
                         and led["totals"]["negative"] == 18
                         and led["totals"]["none"] == 1
                         and not led["errors"])

    # 反向验证（关键）：删掉 §9.1-19 的 4 条判死用例，账本必须变。
    tmp, cut = _copy_without(cases_path, ["45", "46", "47", "48"])
    led_cut = build(cut)
    row19 = [r for r in led_cut["checks"] if r["id"] == "§9.1-19"][0]
    total += 1
    good += _run_fixture("删掉 §9.1-19 的 4 条用例后 coverage 变 none、负例 18→17",
                         row19["coverage"] == "none"
                         and row19["cases"] == 0
                         and led_cut["totals"]["negative"] == 17
                         and led_cut["totals"]["none"] == 2)
    shutil.rmtree(tmp, ignore_errors=True)

    # 只有正例：给扩展位塞一条 rc=0 空期望的基线，应判 positive_only 而非 negative。
    led_pos = build(base + [("x1", "基线", "§9.1-15", [], 0, None)])
    row15 = [r for r in led_pos["checks"] if r["id"] == "§9.1-15"][0]
    total += 1
    good += _run_fixture("只有正例 → coverage=positive_only（不算覆盖）",
                         row15["coverage"] == "positive_only"
                         and led_pos["totals"]["positive_only"] == 1
                         and led_pos["totals"]["none"] == 0)

    # warn 级：基线不算覆盖，必须真的断言告警文本。
    no_warn = [c for c in base if c[0] != "26"]
    led_w0 = build(no_warn)
    led_w1 = build(no_warn + [("x2", "告警", "§9.1-12", ["stale"], 0, None)])
    r0 = [r for r in led_w0["checks"] if r["id"] == "§9.1-12"][0]
    r1 = [r for r in led_w1["checks"] if r["id"] == "§9.1-12"][0]
    total += 1
    good += _run_fixture("warn 级：无告警用例=none，有告警断言=negative",
                         r0["coverage"] == "none" and r1["coverage"] == "negative")

    # 未登记编号必须 FAIL，不能静默忽略。
    led_unknown = build(base + [("x3", "未知", "§9.1-99", ["x"], 1, None)])
    total += 1
    good += _run_fixture("未登记 §9.1-99 → 报错",
                         any("§9.1-99" in e for e in led_unknown["errors"]))

    # DESIGN 行数不一致必须 FAIL。
    led_bad_doc = build(base, design_text=_design_text(18))
    total += 1
    good += _run_fixture("DESIGN §9.1 只有 18 行 → 报错",
                         any("DESIGN" in e for e in led_bad_doc["errors"]))
    led_ok_doc = build(base, design_text=_design_text(19))
    total += 1
    good += _run_fixture("DESIGN §9.1 19 行 → 通过", not led_ok_doc["errors"])

    print("=" * 60)
    print("%s：判据账本自检 %d/%d" % ("✅" if good == total else "❌", good, total))
    return 1 if good != total else 0


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--cases", default=DEFAULT_CASES)
    ap.add_argument("--design", default=None)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    cases = load_cases(a.cases)
    design = None
    design_path = a.design
    if design_path is None and os.path.exists(DEFAULT_DESIGN):
        design_path = DEFAULT_DESIGN
    if design_path and os.path.exists(design_path):
        with open(design_path, encoding="utf-8") as fh:
            design = fh.read()
    ledger = build(cases, design_text=design)
    if design_path:
        ledger["design_check"]["path"] = design_path

    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(ledger, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    if a.json:
        print(json.dumps(ledger, ensure_ascii=False, indent=2))
    else:
        print(summary_of(ledger))
    for e in ledger["errors"]:
        print("❌ " + e, file=sys.stderr)
    return 1 if ledger["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
