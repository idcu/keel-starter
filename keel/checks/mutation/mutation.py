#!/usr/bin/env python3
"""mutation.py —— 判据变异测试试点（DESIGN.md §9.1 / 本轮新增）

用法：
    python3 keel/checks/mutation/mutation.py [--out mutation.json] [--jobs N] [-v]
    bash    keel/checks/mutation/run.sh [--out mutation.json] [--jobs N] [-v]

做什么：对 `keel-lint.sh` 里**可机械注入**的 fail 分支造变异体（条件取反 /
边界偏移 / 删 fail 分支），在独立的 keel 树副本上跑对应判死用例，
**变异体必须让用例变红**（被杀）。输出「被杀 / 总数」与未杀清单。

为什么：判据账本证明「每条判据有一条用例」，但证明不了「用例能判死实现」——
一条只断言"退出码非 0"的用例，在判据被换成 `exit 1` 时照样通过。
变异测试是唯一能测「用例 ↔ 判据」耦合强度的机械手段。

诚实边界（本轮要写进报告，避免下轮把它当万能药）：
    ✓ 抓得到：判据条件被放宽/取反/整段删除，而用例仍然绿——即用例不能判死实现。
    ✗ 抓不到：接线错（入口没被调用，见 checks/wiring/）、判据逻辑正确但**语义**错
      （例如把"超 100 行"改成"超 200 行"恰好没有被任何 fixture 命中）、
      跨文件/跨版本行为（升级、安装、发布链路）。
    因此得分低是**结论**，不是缺陷；也不允许为了抬分筛掉难杀的变异体。

退出码：0 = 全部变异体被杀；1 = 有存活变异体或变异未能注入；2 = 环境错误。
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
KEEL = os.path.dirname(os.path.dirname(HERE))
PY = sys.executable


def read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


# ---------------- 变异体定义 ----------------
# (编号, 判据, 算子, 原文, 替换为, 关联判死用例)
# 原文必须逐字出现在 keel-lint.sh 中；找不到 = 变异未注入（计未杀，不静默跳过）。
MUTANTS = [
    ("M01", "§9.1-1", "delete_fail",
     '    [ "$n" -gt "$lim" ]  && fail_msg "超行数 ${n}>${lim}: $rel"',
     '    :', ["00", "01"]),
    ("M02", "§9.1-1", "boundary_shift",
     '    [ "$n" -gt "$lim" ]  && fail_msg "超行数 ${n}>${lim}: $rel"',
     '    [ "$n" -gt "$((lim * 2))" ]  && fail_msg "超行数 ${n}>${lim}: $rel"',
     ["00", "01"]),
    ("M03", "§9.1-1", "delete_fail",
     '    [ "$b" -gt "$blim" ] && fail_msg "超字节 ${b}>${blim}: $rel"',
     '    :', ["00", "02"]),
    ("M04", "§9.1-2", "boundary_shift",
     '  [ "$nl" -gt 10 ] && fail_msg "frontmatter 超行数 ${nl}>10: $REL"',
     '  [ "$nl" -gt 20 ] && fail_msg "frontmatter 超行数 ${nl}>10: $REL"',
     ["00", "04"]),
    ("M05", "§9.1-2", "delete_fail",
     '  [ -n "$S2_hkw" ] || fail_msg "frontmatter 缺 keywords: $REL"',
     '  :', ["00", "06"]),
    ("M06", "§9.1-3", "delete_fail",
     '    [ -e "$dir/$t" ] || echo "❌ 死链: $t  (见 ${f#"$KEEL_DIR"/})"',
     '    :', ["00", "22"]),
    ("M07", "§9.1-4", "delete_fail",
     '  grep -qxF "$f" "$refd" || fail_msg "孤儿（未被任何热区文档链接引用）: ${f#"$KEEL_DIR"/}"',
     '  :', ["00", "23", "37"]),
    ("M08", "§9.1-6", "delete_fail",
     '    *) fail_msg "status 值域非法（${_s3_st}）: $rel" ;;',
     '    *) ;;', ["00", "07"]),
    ("M09", "§9.1-6", "delete_fail",
     '  case "${_s3_kw:-}" in ""|"[]"|"[ ]") fail_msg "keywords 为空: $rel" ;; esac',
     '  :', ["00", "09"]),
    ("M10", "§9.1-10", "delete_fail",
     '  [ -f "$KEEL_DIR/$need" ] || fail_msg "缺必读文件: $need"',
     '  :', ["00", "17", "49", "50"]),
    ("M11", "§9.1-10", "delete_fail",
     '[ "$anchor_ok" -eq 1 ] || fail_msg "点火锚点缺失或与 §4.1 原文不一致（查 CLAUDE.md / AGENTS.md / .cursorrules / .cursor/rules）"',
     ' :', ["00", "21"]),
    ("M12", "§9.1-17", "invert_condition",
     '        [ "$_badge" = "$_v" ] || fail_msg "README 徽章版本 ${_badge} 与 keel-version ${_v} 不一致（§9.1-14）: ${_rd#"$PWD"/}"',
     '        [ "$_badge" != "$_v" ] || fail_msg "README 徽章版本 ${_badge} 与 keel-version ${_v} 不一致（§9.1-14）: ${_rd#"$PWD"/}"',
     ["00", "39", "41"]),
    ("M13", "§9.1-17", "boundary_shift",
     '          grep -qE "^## ${_v} —" "$_cl" \\',
     '          grep -qE "^## " "$_cl" \\',
     ["00", "40"]),
    ("M14", "§9.1-18", "invert_condition",
     'if [ -n "$_crlf" ]; then',
     'if [ -z "$_crlf" ]; then',
     ["00", "43"]),
    ("M15", "§9.1-19", "delete_fail",
     '      cp) fail_msg "未受控的直写：裸 cp/mv/install（应走 atomic_write，或标 # keel-write:ok）: checks/keel-upgrade.sh:${_wn}" ;;',
     '      cp) ;;', ["00", "45"]),
    ("M16", "§9.1-19", "delete_fail",
     '      fail_msg "成功信息早于终态校验（final_verify 应在「升级完成」前 8 行内）: checks/keel-upgrade.sh:${_wok}"',
     '      :', ["00", "48"]),
]

# 选中的判据与算子分布（报告里逐条写明）：
#   §9.1-1 超行数/超字节（delete ×2, boundary ×1）
#   §9.1-2 frontmatter 行数/缺字段（boundary ×1, delete ×1）
#   §9.1-3 死链（delete ×1）
#   §9.1-4 孤儿（delete ×1）
#   §9.1-6 status 值域 / keywords 为空（delete ×2）
#   §9.1-10 必读文件 / 点火锚点（delete ×2）
#   §9.1-17 徽章一致性 / CHANGELOG 小节（invert ×1, boundary ×1）
#   §9.1-18 CRLF（invert ×1）
#   §9.1-19 裸 cp / 成功信息顺序（delete ×2）

EXCLUDED = [
    ("§9.1-5", "三段式缺失：多段 grep 聚合，删任一条与 §9.1-2 的「字段存在性」同型；本轮按检查类型抽样，同类只保留代表"),
    ("§9.1-7", "索引登记：两段式（grep 索引 + awk 表格），断单行只能测到登记分支；与 §9.1-4 的链接/登记图同型"),
    ("§9.1-8", "命名规则：含文件系统大小写敏感性交互（用例 44 在 macOS 默认盘上跳过），跨平台非确定；环境噪声会污染得分"),
    ("§9.1-9", "引用环：依赖可选工具 tsort，缺 tsort 时判据本身 SKIP；变异体存活会变成环境噪声，读不出用例强弱"),
    ("§9.1-11", "状态机例外：ADR 例外字段多分支，断单条与 §9.1-6 的值域检查同型"),
    ("§9.1-12", "陈旧告警：warn_msg，退出码仍为 0；试点只做 fail 级判据。杀了也只证明「少一条告警」，不是「放过坏输入」"),
    ("§9.1-13", "待蒸馏：阈值告警，同 §9.1-12，非 fail 级"),
    ("§9.1-14", "superseded 指向：目标文件存在性，与 §9.1-4 同型"),
    ("§9.1-15", "项目扩展位：内核不实现，没有可变异的代码"),
    ("§9.1-16", "钩子本体：文件存在性，与 §9.1-10 同型"),
    ("§9.3 meta", "DOC/LOCALE/PROSE/BUDGET 元检查：其判死用例构造的是文档/脚本副本，注入变异需要另一套 fixture 工厂；本轮先守住内核判据，留给下一轮"),
]


def case_ids(union):
    return ",".join(sorted(union, key=lambda x: int(x)))


def run(cmd, cwd, timeout=180):
    p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, timeout=timeout)
    return p.returncode, p.stdout.decode("utf-8", "replace")


def copy_tree(root, name):
    d = os.path.join(root, name)
    shutil.copytree(KEEL, os.path.join(d, "keel"))
    return d


def run_case_subset(d, ids):
    return run([PY, os.path.join(d, "keel/checks/test-lint.py"),
                "--only", case_ids(ids)], cwd=d)


FAIL_RE = re.compile(r"^\[FAIL\] (\S+)", re.M)


def baseline(root):
    all_ids = {c for m in MUTANTS for c in m[5]}
    d = copy_tree(root, "baseline")
    rc, out = run_case_subset(d, all_ids)
    if rc != 0:
        return False, "未变异基线不绿：rc=%d\n%s" % (rc, out[-800:])
    fails = FAIL_RE.findall(out)
    if fails:
        return False, "未变异基线有 FAIL：%s" % fails
    return True, "基线 %d 例全绿" % len(all_ids)


def one_mutant(root, m):
    mid, ref, op, old, new, ids = m
    d = copy_tree(root, mid)
    path = os.path.join(d, "keel/checks/keel-lint.sh")
    text = read(path)
    if old not in text:
        return {"id": mid, "ref": ref, "operator": op, "killed": False,
                "status": "invalid", "by": [],
                "detail": "变异锚点未找到（脚本已漂移）"}
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text.replace(old, new, 1))
    rc, out = run_case_subset(d, ids)
    fails = FAIL_RE.findall(out)
    hit = [c for c in fails if c in ids]
    killed = rc != 0 and bool(hit)
    return {"id": mid, "ref": ref, "operator": op, "killed": killed,
            "status": "killed" if killed else ("survived" if rc != 0 or not hit else "survived"),
            "by": hit, "rc": rc,
            "detail": ("" if killed else
                       ("用例仍绿（变异体存活）" if rc == 0 else
                        "变红但不是目标用例：%s" % fails))}


def main():
    ap = argparse.ArgumentParser(description="判据变异测试试点")
    ap.add_argument("--out", default="")
    ap.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1))
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    root = tempfile.mkdtemp(prefix="keel-mut-")
    t0 = time.time()
    print("判据变异测试（试点）· 变异体 %d 个 · 判据 %d 条 · 算子 %s · 并行 %d"
          % (len(MUTANTS), len({m[1] for m in MUTANTS}),
             "、".join(sorted({m[2] for m in MUTANTS})), a.jobs))
    print("=" * 78)

    ok, msg = baseline(root)
    if not ok:
        print("❌ 基线自检失败：%s" % msg)
        shutil.rmtree(root, ignore_errors=True)
        return 2
    print("· 基线：%s" % msg)

    results = []
    with futures.ThreadPoolExecutor(max_workers=a.jobs) as ex:
        for r in ex.map(lambda m: one_mutant(root, m), MUTANTS):
            results.append(r)
            mark = {"killed": "KILLED", "survived": "SURVIVED", "invalid": "INVALID"}[r["status"]]
            extra = ("by %s" % ",".join(r["by"])) if r["by"] else r["detail"]
            print("[%-8s] %s %-8s %-17s %s" % (mark, r["id"], r["ref"], r["operator"], extra))

    killed = sum(1 for r in results if r["status"] == "killed")
    invalid = sum(1 for r in results if r["status"] == "invalid")
    survived = [r for r in results if r["status"] != "killed"]
    duration = round(time.time() - t0, 1)

    print("=" * 78)
    print("变异得分：%d/%d 被杀（%.1f%%）· 存活 %d · 未注入 %d · %.1fs"
          % (killed, len(results), 100.0 * killed / len(results),
             len(survived) - invalid, invalid, duration))
    if survived:
        print("存活清单（低分是结论，不许为抬分删掉它们）：")
        for r in survived:
            print("  - %s %s %s：%s" % (r["id"], r["ref"], r["operator"], r["detail"]))
    print("· 试点的诚实边界：抓不到接线错、语义正确但判据放宽没被 fixture 命中、跨文件/跨版本行为。")

    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump({
                "schema": 1,
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "totals": {"mutants": len(results), "killed": killed,
                           "survived": len(results) - killed - invalid,
                           "invalid": invalid,
                           "score_pct": round(100.0 * killed / len(results), 1)},
                "mutants": results,
                "selected": sorted({m[1] for m in MUTANTS}),
                "excluded": [{"ref": r, "reason": why} for r, why in EXCLUDED],
                "operators": sorted({m[2] for m in MUTANTS}),
                "duration_s": duration,
                "boundary": "抓不到接线错、语义正确但判据放宽未被 fixture 命中、跨文件/跨版本行为",
            }, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        print("   变异结果已写入：%s" % a.out)

    shutil.rmtree(root, ignore_errors=True)
    return 0 if killed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
