---
scope: db
status: active
severity: P1
last-verified: 2026-09-30
triggers: 0
keywords: [连接池, 超时, 连接池耗尽, connection pool]
---

## 症状

压测下接口大面积 500，日志报 `connection pool exhausted`。

## 根因

DAO 层在循环内新建连接，未走连接池单例；连接数上限 20，QPS>50 即耗尽。

## 正解

- 连接必须走全局连接池，禁止在循环内建连
- 池大小 = CPU 核数 × 2 + 有效磁盘数
- 超时时间必须显式设置，禁用默认 0（无限等待）
