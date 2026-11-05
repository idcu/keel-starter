#!/usr/bin/env python3
"""checks-ledger.py —— 判据账本与可复算的判据遵守率（DESIGN §9.1 / §12.3）

用法：
    python3 keel/checks/verify/checks-ledger.py --summary
    python3 keel/checks/verify/checks-ledger.py --json [--out checks-ledger.json]
    python3 keel/checks/verify/checks-ledger.py --selftest
    python3 keel/checks/verify/checks-ledger.py --recompute   # 外人复算入口
    python3 keel/checks/verify/checks-ledger.py --check       # 门禁用：账本过期即 rc=1
    python3 keel/checks/verify/checks-ledger.py --regen       # 重新生成 ledger.tsv
    python3 keel/checks/verify/checks-ledger.py --negctl      # 三条负控实跑

口径（正文在 DESIGN §12.3「判据账本口径」，本文件只实现，不另立定义）：
    * 枚举真源 = checks/verify/criteria.tsv，一条判据一行；分母 = 该口径下 counted=yes 的行数。
    * D1 仅 §9.1；D2 = D1 + 元检查；D3 = D2 + §9.3 预算检查。三个分母同时打印。
    * PASS = coverage=negative（fail 级有 rc=1 判死用例；warn 级有断言告警文本的用例）。
    * SKIP = coverage 为 positive_only / none；SKIP 进分母、不进分子。
    * EXCLUDED = criteria.tsv 的 counted=no；不进任何分母，必须写理由；§9.1 判据不得排除。
    * 证据指针指到 test-lint.py 的具体用例 ID（CASES:… / META:…）。
    * 账本 checks/verify/ledger.tsv 是生成物并入库；--check 逐字节比对，任何手改即红。
"""

import argparse
import datetime
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
sys.dont_write_bytecode = True   # 账本会给仓库留下 __pycache__，把 provenance 的 dirty 假阳性
import tempfile
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
KEEL = os.path.dirname(os.path.dirname(HERE))
REPO = os.path.dirname(KEEL)
DEFAULT_CASES = os.path.join(KEEL, "checks", "test-lint.py")
DEFAULT_CRITERIA = os.path.join(HERE, "criteria.tsv")
DEFAULT_LEDGER = os.path.join(HERE, "ledger.tsv")
DEFAULT_DESIGN = os.path.join(REPO, "DESIGN.md")

# test-lint 历史上用 "§9.3" 指预算检查（用例 20），保留别名，不要求改用例编号。
EXTRA_ALIAS = {"§9.3": "§9.3-BUDGET"}
AUX_NOTES = {
    "§3.4": "命名豁免的合法基线（支持性用例，不是独立检查项）",
    "§6.1": "frontmatter 行内注释的合法基线",
    "§9.4": "陈旧豁免的合法基线",
    "§12.1": "MVP 全绿基线",
}


def sha256_of(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def load_criteria(path):
    """读 criteria.tsv。不做隐式纠错：坏行就是坏行，交给 validate 判死。"""
    rows = []
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.rstrip("\n")
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) != 6:
                raise ValueError("%s:%d 列数=%d，应为 6" % (path, lineno, len(parts)))
            cid, section, level, kind, counted, title = parts
            rows.append({"id": cid, "section": section, "level": level,
                         "kind": kind, "counted": counted, "title": title})
    return rows


def load_cases(path):
    """导入 test-lint.py，直接读 CASES 与 META_CASES —— 不解析文本、不维护第二份清单。"""
    name = "keel_cases_%s" % uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return list(mod.CASES), list(getattr(mod, "META_CASES", []))


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


def _validate_criteria(criteria):
    errors = []
    ids = [r["id"] for r in criteria]
    if len(set(ids)) != len(ids):
        errors.append("判据编号重复")
    for r in criteria:
        if r["kind"] not in ("rule", "meta", "aux"):
            errors.append("%s 的 kind=%s 非法（应为 rule/meta/aux）" % (r["id"], r["kind"]))
        if r["counted"] not in ("yes", "no"):
            errors.append("%s 的 counted=%s 非法（应为 yes/no）" % (r["id"], r["counted"]))
        if r["kind"] == "rule" and r["section"] != "§9.1":
            errors.append("%s 是 rule 但 section=%s（应为 §9.1）" % (r["id"], r["section"]))
        if r["kind"] in ("meta", "aux") and r["section"] != "§9.3":
            errors.append("%s 是 %s 但 section=%s（应为 §9.3）" % (r["id"], r["kind"], r["section"]))
        if r["kind"] == "rule" and r["level"] not in ("fail", "warn", "extension"):
            errors.append("%s 的 level=%s 非法" % (r["id"], r["level"]))
        if r["kind"] in ("meta", "aux") and r["level"] not in ("fail", "meta"):
            errors.append("%s 的 level=%s 非法" % (r["id"], r["level"]))
    # §9.1 必须是连续编号，且不得被移出分母——那是改口径，只能走新口径 + ADR。
    rule_nums = []
    for r in criteria:
        if r["section"] != "§9.1":
            continue
        m = re.match(r"^§9\.1-(\d+)$", r["id"])
        if not m:
            errors.append("§9.1 判据编号不符合 §9.1-N：%s" % r["id"])
            continue
        rule_nums.append(int(m.group(1)))
        if r["counted"] != "yes":
            errors.append("%s 被排除出分母：§9.1 判据不得 counted=no（改口径须 ADR）" % r["id"])
    if rule_nums and sorted(rule_nums) != list(range(1, max(rule_nums) + 1)):
        errors.append("§9.1 判据编号不连续（缺 %s）"
                      % ",".join(map(str, sorted(set(range(1, max(rule_nums) + 1))
                                               - set(rule_nums)))))
    if not rule_nums:
        errors.append("criteria.tsv 里没有任何 §9.1 判据")
    return errors


def build(criteria, cases, design_text=None, meta_cases=None):
    meta_cases = meta_cases or []
    errors = _validate_criteria(criteria)

    known = {r["id"] for r in criteria} | set(EXTRA_ALIAS)
    for ref in sorted({c[2] for c in cases}):
        if re.match(r"§9\.1-\d+$", ref) and ref not in known:
            errors.append("test-lint 引用了未登记的判据：%s" % ref)
        if ref.startswith("§9.3-") and ref not in known:
            errors.append("test-lint 引用了未登记的 §9.3 附加判据：%s" % ref)
    for mc in meta_cases:
        if mc[2] not in known and mc[2] not in EXTRA_ALIAS:
            errors.append("元检查判死用例引用了未登记的判据：%s（%s）" % (mc[2], mc[0]))

    rows = []
    for r in criteria:
        refs = {r["id"]} | {k for k, v in EXTRA_ALIAS.items() if v == r["id"]}
        cs = [c for c in cases if c[2] in refs]
        mc = [c for c in meta_cases if c[2] in refs]
        if r["level"] == "fail":
            negative = sum(1 for c in cs if classify(c) == "death") + len(mc)
        elif r["level"] == "warn":
            negative = sum(1 for c in cs if classify(c) == "warn")
        else:
            negative = 0
        if r["counted"] == "no":
            coverage = "excluded"
            status = "EXCLUDED"
        elif negative:
            coverage = "negative"
            status = "PASS"
        elif cs or mc:
            coverage = "positive_only"
            status = "SKIP"
        else:
            coverage = "none"
            status = "SKIP"

        ev = []
        if cs:
            ev.append("CASES:" + ",".join(sorted(c[0] for c in cs)))
        if mc:
            ev.append("META:" + ",".join(sorted(c[0] for c in mc)))
        evidence = ";".join(ev) if ev else "none"

        if status == "EXCLUDED":
            reason = "不计入分母：无独立判死用例（进自测分母）"
        elif status == "PASS":
            reason = "-"
        elif r["level"] == "extension":
            reason = "扩展位（DESIGN §9.2）：内核不实现，需项目侧判据"
        elif coverage == "positive_only":
            reason = "仅合法基线，无判死用例"
        else:
            reason = "无用例"

        rows.append({
            "id": r["id"], "section": r["section"], "level": r["level"],
            "kind": r["kind"], "counted": r["counted"], "title": r["title"],
            "status": status, "coverage": coverage,
            "cases": len(cs) + len(mc), "negative_cases": negative,
            "death_cases": sum(1 for c in cs if classify(c) == "death") + len(mc),
            "warn_cases": sum(1 for c in cs if classify(c) == "warn"),
            "baseline_cases": sum(1 for c in cs if classify(c) == "baseline"),
            "evidence": evidence, "reason": reason,
        })

    counted = [r for r in rows if r["counted"] == "yes"]
    checks = [r for r in rows if r["section"] == "§9.1"]
    extras = [r for r in counted if r["section"] != "§9.1"]
    excluded = [r for r in rows if r["counted"] == "no"]

    negative = sum(1 for r in checks if r["coverage"] == "negative")
    positive_only = sum(1 for r in checks if r["coverage"] == "positive_only")
    none = sum(1 for r in checks if r["coverage"] == "none")
    if negative + positive_only + none != len(checks):
        errors.append("三档之和 != §9.1 判据总数")
    implemented = sum(1 for r in checks if r["level"] != "extension")
    extension = len(checks) - implemented

    def _uni(rows_part):
        # 分母只从行数推导。这里的 len() 是唯一来源，任何字面量都视为口径被改。
        ids = [r["id"] for r in rows_part if r["counted"] == "yes"]
        den = len(ids)
        neg = sum(1 for r in rows_part if r["counted"] == "yes" and r["coverage"] == "negative")
        return {"denominator": den, "negative": neg, "denominator_ids": ids,
                "coverage_pct": round(neg * 100.0 / den, 1) if den else 0.0}

    d1 = _uni(checks)
    d2 = _uni(checks + [r for r in extras if r["kind"] == "meta"])
    d3 = _uni(checks + extras)
    if d1["denominator"] != len(checks):
        errors.append("D1 分母与 §9.1 判据条数不一致")
    if d3["denominator"] != len(counted):
        errors.append("D3 分母与 counted=yes 条数不一致")

    design_check = {"path": None, "status": "skipped", "rows": None,
                    "reason": "未提供 DESIGN.md（采用方环境）"}
    if design_text is not None:
        design_check["status"] = "checked"
        design_check["reason"] = None
        nums_in_doc = parse_design_91(design_text)
        if nums_in_doc is None:
            errors.append("DESIGN 找不到 §9.1 小节")
        else:
            doc_set = set(nums_in_doc)
            led_set = set(int(re.match(r"^§9\.1-(\d+)$", r["id"]).group(1))
                          for r in checks if re.match(r"^§9\.1-(\d+)$", r["id"]))
            missing = sorted(doc_set - led_set)
            extra = sorted(led_set - doc_set)
            if missing:
                errors.append("DESIGN §9.1 有条目未进账本：%s"
                              % ",".join("§9.1-%d" % n for n in missing))
            if extra:
                errors.append("账本有条目不在 DESIGN §9.1：%s"
                              % ",".join("§9.1-%d" % n for n in extra))
            if len(nums_in_doc) != len(led_set):
                errors.append("DESIGN §9.1 行数 %d 与账本 §9.1 条数 %d 不一致"
                              % (len(nums_in_doc), len(led_set)))
        design_check["rows"] = len(nums_in_doc) if nums_in_doc else 0

    meta = [{"id": r["id"], "counted_in_selftest_total": r["id"] in ("NOISE", "INVOKE"),
             "note": r["title"]} for r in rows if r["kind"] == "meta"]

    aux = []
    for ref in sorted({c[2] for c in cases
                       if not c[2].startswith("§9.1-") and c[2] not in known}):
        cs = [c for c in cases if c[2] == ref]
        aux.append({
            "id": ref,
            "note": AUX_NOTES.get(ref, "未登记的辅助用例引用"),
            "cases": len(cs),
            "negative_cases": sum(1 for c in cs if classify(c) in ("death", "warn")),
            "baseline_cases": sum(1 for c in cs if classify(c) == "baseline"),
        })

    return {
        "schema": 1,
        "generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "scope": {
            "numbered_ids": d1["denominator_ids"],
            "D1": "仅 §9.1 = §9.1 行数（由 criteria.tsv 推导）",
            "D2": "§9.1 + 元检查（kind=meta）",
            "D3": "§9.1 + 元检查 + 预算真源（kind=aux）",
            "excludes": [r["id"] for r in excluded],
            "out_of_scope": ["动态套件（test-upgrade/test-faults/matrix）"],
        },
        "design_check": design_check,
        "totals": {
            "numbered": len(checks),
            "implemented": implemented,
            "extension": extension,
            "negative": negative,
            "negative_fail_level": sum(1 for r in checks
                                       if r["level"] == "fail" and r["negative_cases"] > 0),
            "negative_warn_level": sum(1 for r in checks
                                       if r["level"] == "warn" and r["negative_cases"] > 0),
            "positive_only": positive_only,
            "none": none,
            "coverage_pct_of_numbered": d1["coverage_pct"],
            "coverage_pct_of_implemented": round(negative * 100.0 / implemented, 1) if implemented else 0.0,
            "status": {"PASS": sum(1 for r in rows if r["status"] == "PASS"),
                       "SKIP": sum(1 for r in rows if r["status"] == "SKIP"),
                       "EXCLUDED": sum(1 for r in rows if r["status"] == "EXCLUDED")},
            "with_meta": d2,
            "all": d3,
        },
        "checks": checks,
        "extras": extras,
        "excluded": excluded,
        "all_rows": rows,
        "auxiliary": aux,
        "meta": meta,
        "out_of_scope": ["test-upgrade", "test-faults", "matrix"],
        "errors": errors,
    }


def serialize_ledger(ledger):
    """账本的唯一序列化形式：无时间戳、无环境信息，逐字节可复算。"""
    lines = [
        "# keel-criteria-ledger v1",
        "# 口径：DESIGN §12.3「判据账本口径」；生成：checks/verify/checks-ledger.py --regen",
        "# 分母由本账本 counted=yes 的行数推导，不写常量；复算：checks-ledger.py --recompute",
        "# 列：id<TAB>section<TAB>level<TAB>kind<TAB>counted<TAB>status<TAB>coverage<TAB>cases<TAB>negative_cases<TAB>evidence<TAB>reason",
    ]
    for r in ledger["all_rows"]:
        lines.append("\t".join(str(r[k]) for k in
                               ("id", "section", "level", "kind", "counted", "status",
                                "coverage", "cases", "negative_cases", "evidence", "reason")))
    return "\n".join(lines) + "\n"


def check_ledger(ledger, ledger_path):
    """已提交账本必须逐字节等于复算结果；手改（含写死分母）一律判死。"""
    errors = []
    expected = serialize_ledger(ledger)
    if not os.path.isfile(ledger_path):
        errors.append("账本缺失：%s（先跑 --regen）" % ledger_path)
        return expected, errors
    with open(ledger_path, encoding="utf-8") as fh:
        actual = fh.read()
    if actual != expected:
        errors.append("账本与复算不一致：%s（期望 sha256=%s，实际 sha256=%s）"
                      % (ledger_path, hashlib.sha256(expected.encode()).hexdigest()[:16],
                         hashlib.sha256(actual.encode()).hexdigest()[:16]))
    # 显式识别「分母被写成整数常量」：生成物不该出现 total/denominator 行。
    for m in re.finditer(r"^#\s*denominator\s+D(\d)\s*=\s*(\d+)\s*$", actual, re.M):
        level, declared = "D" + m.group(1), int(m.group(2))
        real = {"D1": ledger["totals"]["numbered"],
                "D2": ledger["totals"]["with_meta"]["denominator"],
                "D3": ledger["totals"]["all"]["denominator"]}.get(level)
        if real is None:
            errors.append("账本声明了未知口径 %s" % level)
        elif declared != real:
            errors.append("账本写死分母 %s=%d，清单推导为 %d（常量分母不许篡改）"
                          % (level, declared, real))
    return expected, errors


def summary_of(ledger):
    t = ledger["totals"]
    wm = t["with_meta"]
    al = t["all"]
    zeros = [r for r in ledger["checks"] + ledger.get("extras", [])
             if r["coverage"] in ("none", "positive_only")]
    lines = [
        "判据遵守率（D1 仅 §9.1）：%d/%d（%.1f%%，其中 %d 判死 + %d 告警；按已实现 %d/%d）"
        % (t["negative"], t["numbered"], t["coverage_pct_of_numbered"],
           t["negative_fail_level"], t["negative_warn_level"],
           t["negative"], t["implemented"]),
        "判据遵守率（D2 含元检查）：%d/%d（%.1f%%）" %
        (wm["negative"], wm["denominator"], wm["coverage_pct"]),
        "判据遵守率（D3 含 §9.3 预算检查）：%d/%d（%.1f%%）" %
        (al["negative"], al["denominator"], al["coverage_pct"]),
        "  - 分解：D1 %d/%d + 元检查 %d/%d + 预算真源 %d/%d"
        % (t["negative"], t["numbered"],
           sum(1 for r in ledger.get("extras", [])
               if r["kind"] == "meta" and r["coverage"] == "negative"),
           sum(1 for r in ledger.get("extras", []) if r["kind"] == "meta"),
           sum(1 for r in ledger.get("extras", [])
               if r["kind"] == "aux" and r["coverage"] == "negative"),
           sum(1 for r in ledger.get("extras", []) if r["kind"] == "aux")),
        "  - §9.1 三档：负例 %d · 只有正例 %d · 无用例 %d"
        % (t["negative"], t["positive_only"], t["none"]),
        "  - 状态：PASS %d · SKIP %d · EXCLUDED %d（分母只数 counted=yes）"
        % (t["status"]["PASS"], t["status"]["SKIP"], t["status"]["EXCLUDED"]),
    ]
    if zeros:
        lines.append("  - 未覆盖（SKIP）：%s"
                     % "；".join("%s（%s）" % (r["id"], r["reason"]) for r in zeros))
    else:
        lines.append("  - 未覆盖（SKIP）：无")
    excluded = ledger.get("excluded") or []
    if excluded:
        lines.append("  - 不计入分母（EXCLUDED）：%s"
                     % "；".join("%s（%s）" % (r["id"], r["reason"]) for r in excluded))
    if ledger["design_check"]["status"] == "checked":
        lines.append("  - DESIGN §9.1 对齐：%s 行" % ledger["design_check"]["rows"])
    else:
        lines.append("  - DESIGN §9.1 对齐：SKIP（%s）" % ledger["design_check"]["reason"])
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
    drop_prefix = tuple('@case("%s"' % i for i in ids) + \
                  tuple('@mcase("%s"' % i for i in ids)
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


def _tsv_without(src, dst, ids):
    with open(src, encoding="utf-8") as fh:
        lines = [l for l in fh if not any(l.startswith(i + "\t") for i in ids)]
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write("".join(lines))


def _load_design(path):
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    return None


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def negctl(criteria_path, ledger_path, cases_path, design_path=None, quiet=False):
    """三条负控必须真判死。返回 (killed, results)。"""
    tmp = tempfile.mkdtemp(prefix="keel-negctl-")
    cases, meta = load_cases(cases_path)
    design = _load_design(design_path)
    results = []

    def run(name, crit_path, led_path, design_text, case_list=None):
        rows = load_criteria(crit_path)
        led = build(rows, case_list if case_list is not None else cases,
                    design_text=design_text, meta_cases=meta)
        _, errs = check_ledger(led, led_path)
        bad = led["errors"] + errs
        results.append((name, bool(bad), bad))
        if not quiet:
            print("[%s] %s" % ("KILLED" if bad else "SURVIVED", name))
            for e in bad[:4]:
                print("    " + e)

    # 1) 分母被写成整数常量：清单与账本都是 18 行，只有头部写死 D1=19。
    #    这一格必须只由「常量分母」判死，否则证明不了常量本身被拦。
    c1 = os.path.join(tmp, "criteria-const.tsv")
    _tsv_without(criteria_path, c1, ["§9.1-19"])
    tmpc1, (cases1, meta1) = _copy_without(cases_path, ["45", "46", "47", "48"])
    rows1 = load_criteria(c1)
    led1 = build(rows1, cases1, design_text=_design_text(18), meta_cases=meta1)
    l1 = os.path.join(tmp, "ledger-const.tsv")
    with open(l1, "w", encoding="utf-8") as fh:
        fh.write("# denominator D1=19\n" + serialize_ledger(led1))
    run("负控1 恒定分母（清单 18 行 + 写死 D1=19）", c1, l1, _design_text(18), cases1)
    shutil.rmtree(tmpc1, ignore_errors=True)

    # 2) 某条判据被悄悄删掉：清单、用例、账本三处都少 §9.1-9，账本自洽，
    #    但 DESIGN 仍是 19 行——只靠「重新生成账本」藏不住。
    c2 = os.path.join(tmp, "criteria-cut.tsv")
    _tsv_without(criteria_path, c2, ["§9.1-9"])
    tmpc2, (cases2, meta2) = _copy_without(cases_path, ["16"])
    rows2 = load_criteria(c2)
    led2 = build(rows2, cases2, design_text=design, meta_cases=meta2)
    l2 = os.path.join(tmp, "ledger-cut.tsv")
    with open(l2, "w", encoding="utf-8") as fh:
        fh.write(serialize_ledger(led2))
    text2 = design if design is not None else _design_text(19)
    run("负控2 悄悄删判据（三处对齐但 DESIGN 仍 19 行）", c2, l2, text2, cases2)
    shutil.rmtree(tmpc2, ignore_errors=True)

    # 3) 账本与规格条目数量对不上：DESIGN §9.1 有 20 行。
    run("负控3 规格条目数不符（DESIGN 20 行 vs 账本 19）",
        criteria_path, ledger_path, _design_text(20))

    shutil.rmtree(tmp, ignore_errors=True)
    killed = sum(1 for _, ok, _ in results if ok)
    if not quiet:
        print("=" * 60)
        print("%s：负控 %d/%d 判死" % ("✅" if killed == len(results) else "❌",
                                     killed, len(results)))
    return killed, results


def selftest(criteria_path, cases_path):
    good = 0
    total = 0
    criteria = load_criteria(criteria_path)
    base, meta = load_cases(cases_path)
    design = _load_design(DEFAULT_DESIGN)
    led = build(criteria, base, design_text=design, meta_cases=meta)
    total += 1
    good += _run_fixture("真实清单：§9.1 连续、全部 counted=yes、无结构错误",
                         not led["errors"]
                         and led["totals"]["numbered"] == len([r for r in criteria
                                                               if r["section"] == "§9.1"])
                         and all(r["counted"] == "yes" for r in criteria
                                 if r["section"] == "§9.1"))
    total += 1
    good += _run_fixture("三个分母由 counted=yes 行数推导，且 D1<D2<D3",
                         led["totals"]["with_meta"]["denominator"]
                         == led["totals"]["numbered"]
                         + sum(1 for r in criteria if r["kind"] == "meta" and r["counted"] == "yes")
                         and led["totals"]["all"]["denominator"]
                         == led["totals"]["with_meta"]["denominator"]
                         + sum(1 for r in criteria if r["kind"] == "aux" and r["counted"] == "yes")
                         and led["totals"]["all"]["denominator"]
                         == sum(1 for r in criteria if r["counted"] == "yes"))

    expected, errs = check_ledger(led, DEFAULT_LEDGER)
    total += 1
    good += _run_fixture("已提交 ledger.tsv 与复算逐字节一致", not errs)

    tmp, (cut, cut_meta) = _copy_without(cases_path, ["45", "46", "47", "48"])
    led_cut = build(criteria, cut, design_text=design, meta_cases=cut_meta)
    row19 = [r for r in led_cut["checks"] if r["id"] == "§9.1-19"][0]
    total += 1
    good += _run_fixture("删掉 §9.1-19 的 4 条用例后 coverage 变 none、分子 -1",
                         row19["coverage"] == "none"
                         and row19["cases"] == 0
                         and led_cut["totals"]["negative"] == led["totals"]["negative"] - 1)
    shutil.rmtree(tmp, ignore_errors=True)

    tmp2, (cut2, cut2_meta) = _copy_without(cases_path, ["§9.3-DOC"])
    led_cut2 = build(criteria, cut2, design_text=design, meta_cases=cut2_meta)
    doc_row = [r for r in led_cut2["extras"] if r["id"] == "§9.3-DOC"][0]
    total += 1
    good += _run_fixture("删掉 §9.3-DOC 判死用例 → SKIP，D2 分子 -1",
                         doc_row["coverage"] == "none"
                         and led_cut2["totals"]["with_meta"]["denominator"]
                         == led["totals"]["with_meta"]["denominator"]
                         and led_cut2["totals"]["with_meta"]["negative"]
                         == led["totals"]["with_meta"]["negative"] - 1)
    shutil.rmtree(tmp2, ignore_errors=True)

    tmp3, (cut3, cut3_meta) = _copy_without(cases_path, ["20"])
    led_cut3 = build(criteria, cut3, design_text=design, meta_cases=cut3_meta)
    bud = [r for r in led_cut3["extras"] if r["id"] == "§9.3-BUDGET"][0]
    total += 1
    good += _run_fixture("删掉 §9.3-BUDGET 判死用例 → D3 分子 -1",
                         bud["coverage"] == "none"
                         and led_cut3["totals"]["all"]["negative"]
                         == led["totals"]["all"]["negative"] - 1)
    shutil.rmtree(tmp3, ignore_errors=True)

    led_pos = build(criteria + [{"id": "x1", "section": "§9.1", "level": "fail",
                                 "kind": "rule", "counted": "yes", "title": "基线"}],
                    base + [("x1c", "基线", "x1", [], 0, None)], meta_cases=meta)
    total += 1
    good += _run_fixture("只有正例 → SKIP（不算 PASS）",
                         any(r["id"] == "x1" and r["status"] == "SKIP"
                             for r in led_pos["checks"]))

    no_warn = [c for c in base if c[0] != "26"]
    led_w0 = build(criteria, no_warn, meta_cases=meta)
    total += 1
    good += _run_fixture("warn 级：无告警断言 → SKIP", any(
        r["id"] == "§9.1-12" and r["coverage"] == "none" for r in led_w0["checks"]))

    led_unknown = build(criteria, base + [("x3", "未知", "§9.1-99", ["x"], 1, None)],
                        meta_cases=meta)
    total += 1
    good += _run_fixture("未登记 §9.1-99 → 报错",
                         any("§9.1-99" in e for e in led_unknown["errors"]))
    led_unknown3 = build(criteria, base, meta_cases=meta + [("mX", "未知", "§9.3-XXX", None)])
    total += 1
    good += _run_fixture("未登记 §9.3-XXX 的判死用例 → 报错",
                         any("§9.3-XXX" in e for e in led_unknown3["errors"]))

    total += 1
    good += _run_fixture("DESIGN §9.1 18 行 → 报错",
                         any("DESIGN" in e for e in build(
                             criteria, base, design_text=_design_text(18),
                             meta_cases=meta)["errors"]))
    total += 1
    good += _run_fixture("DESIGN §9.1 19 行 → 通过",
                         not build(criteria, base, design_text=_design_text(19),
                                   meta_cases=meta)["errors"])

    excl = [dict(r) for r in criteria]
    [r for r in excl if r["id"] == "§9.1-15"][0]["counted"] = "no"
    total += 1
    good += _run_fixture("把 §9.1 判据移出分母 → 报错（不许为好看改分母）",
                         any("§9.1-15" in e and "不得 counted=no" in e
                             for e in build(excl, base, meta_cases=meta)["errors"]))

    total += 1
    bad_led = os.path.join(tempfile.mkdtemp(prefix="keel-led-"), "ledger.tsv")
    with open(bad_led, "w", encoding="utf-8") as fh:
        fh.write(serialize_ledger(led).replace("§9.1-1\t", "§9.1-1X\t", 1))
    _, bad_errs = check_ledger(led, bad_led)
    good += _run_fixture("手改账本（改判据 ID）→ --check 判死", bool(bad_errs))
    shutil.rmtree(os.path.dirname(bad_led), ignore_errors=True)

    killed, _ = negctl(criteria_path, DEFAULT_LEDGER, cases_path, DEFAULT_DESIGN, quiet=True)
    total += 1
    good += _run_fixture("三条负控全部判死（恒定分母 / 悄悄删判据 / 规格条数不符）",
                         killed == 3)

    print("=" * 60)
    print("%s：判据账本自检 %d/%d" % ("✅" if good == total else "❌", good, total))
    return 1 if good != total else 0


def _print_recompute(ledger, criteria_path, ledger_path, expected, errs):
    print("判据账本复算 · criteria=%s · ledger=%s" % (criteria_path, ledger_path))
    print("criteria.tsv sha256 = %s" % sha256_of(criteria_path))
    if os.path.isfile(ledger_path):
        print("ledger.tsv   sha256 = %s" % sha256_of(ledger_path))
    print("期望 ledger  sha256 = %s" % hashlib.sha256(expected.encode()).hexdigest())
    for key, label in (("numbered_ids", "D1（仅 §9.1）"),
                       ("with_meta", "D2（+元检查）"),
                       ("all", "D3（+预算真源）")):
        if key == "numbered_ids":
            ids = ledger["scope"]["numbered_ids"]
            neg = ledger["totals"]["negative"]
        else:
            ids = ledger["totals"][key]["denominator_ids"]
            neg = ledger["totals"][key]["negative"]
        print("%s：%d 条 → %s" % (label, len(ids), " ".join(ids)))
        print("    判据遵守率 %d/%d = %.1f%%" % (neg, len(ids), neg * 100.0 / len(ids)))
    skips = [r for r in ledger["checks"] + ledger["extras"] if r["status"] == "SKIP"]
    print("SKIP（进分母、不进分子）：%s"
          % ("；".join("%s（%s）" % (r["id"], r["reason"]) for r in skips) or "无"))
    excl = ledger["excluded"]
    print("EXCLUDED（不进分母）：%s"
          % ("；".join("%s（%s）" % (r["id"], r["reason"]) for r in excl) or "无"))
    if ledger["design_check"]["status"] == "checked":
        print("DESIGN §9.1 对齐：%d 行，已校验" % ledger["design_check"]["rows"])
    else:
        print("DESIGN §9.1 对齐：SKIP（%s）" % ledger["design_check"]["reason"])
    if errs:
        for e in errs:
            print("❌ " + e)
        print("结论：复算与已提交账本不一致（rc=1）")
    else:
        print("结论：复算与已提交账本逐字节一致（rc=0）")
    return 0 if not errs else 1


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--cases", default=DEFAULT_CASES)
    ap.add_argument("--criteria", default=DEFAULT_CRITERIA)
    ap.add_argument("--ledger", default=DEFAULT_LEDGER)
    ap.add_argument("--design", default=None)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--recompute", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--regen", action="store_true")
    ap.add_argument("--negctl", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest(a.criteria, a.cases)
    if a.negctl:
        killed, _ = negctl(a.criteria, a.ledger, a.cases, a.design or DEFAULT_DESIGN)
        return 0 if killed == 3 else 1

    criteria = load_criteria(a.criteria)
    cases, meta_cases = load_cases(a.cases)
    design_path = a.design
    if design_path is None and os.path.exists(DEFAULT_DESIGN):
        design_path = DEFAULT_DESIGN
    design = _load_design(design_path)
    ledger = build(criteria, cases, design_text=design, meta_cases=meta_cases)
    if design_path:
        ledger["design_check"]["path"] = design_path

    expected, ledger_errs = check_ledger(ledger, a.ledger)
    ledger["artifacts"] = {
        "criteria": a.criteria,
        "criteria_sha256": sha256_of(a.criteria),
        "ledger": a.ledger,
        "ledger_sha256": sha256_of(a.ledger) if os.path.isfile(a.ledger) else None,
        "expected_ledger_sha256": hashlib.sha256(expected.encode()).hexdigest(),
    }
    if a.regen:
        if ledger["errors"]:
            for e in ledger["errors"]:
                print("❌ " + e, file=sys.stderr)
            return 1
        with open(a.ledger, "w", encoding="utf-8") as fh:
            fh.write(expected)
        print("已生成 %s（sha256=%s）"
              % (a.ledger, hashlib.sha256(expected.encode()).hexdigest()))
        return 0
    if a.recompute:
        return _print_recompute(ledger, a.criteria, a.ledger, expected,
                                ledger["errors"] + ledger_errs)
    if a.check:
        errs = ledger["errors"] + ledger_errs
        for e in errs:
            print("❌ " + e)
        if not errs:
            print("✅ 账本自洽：%s" % a.ledger)
        return 1 if errs else 0

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
