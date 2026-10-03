---
scope: meta
status: active
severity: P2
last-verified: 2026-10-03
triggers: 0
keywords: [JSON, null, 字符串, 合法, 手写, 解析失败, 分母为零]
---

## 症状

`compliance.sh report --json` 无数据时输出 `"rate":"n/a"`（**字符串**）。
喂给 `jq` / `node -e` / `json.load()` → **解析失败**。

## 根因

手写 JSON 时"没有值"顺手写成 `"n/a"` 占位串——**JSON 没有 NaN/NA，只有 `null`**。
正确：`"rate":null`（裸 null，不是字符串）。

## 正解

```bash
local rate_json="null"            # 给 JSON 的只能是裸 null
if [ "$rounds" -gt 0 ]; then rate_json=$(awk -v v="$x" -v r="$r" 'BEGIN{printf "%.1f",(1-v/r)*100}'); fi
printf '{"rate":%s}\n' "$rate_json"     # %s 不加引号
```

**自检**：输出 JSON 的脚本都用真解析器过一遍（`json.load(sys.stdin)`），
比肉眼看括号可靠。同一 `report` 里 `coverage`/`loadOverRate` 同理。
