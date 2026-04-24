# Feishu Message Adjustments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 调整飞书盘后消息格式，恢复最新交易日情绪指标分组，并在十日趋势行中补充 `<20H> / <20L> / <60H> / <60L>` 字段。

**Architecture:** 仅修改飞书文本拼装层，不改指标计算和数据来源。先通过单元测试定义新的输出结构，再在 `FeishuNotificationService` 中做最小实现，最后跑相关测试与全量测试确认无回归。

**Tech Stack:** Python 3.10+, pytest, requests

---

### Task 1: Update Feishu Message Formatting

**Files:**
- Modify: `D:\Program_python\free_stock\tests\unit\test_market_close_job.py`
- Modify: `D:\Program_python\free_stock\src\gmtrade_live\services\feishu_notification_service.py`

- [ ] **Step 1: Write the failing test**

更新 `test_feishu_build_message_uses_summary_first_and_keeps_trend_lines()`，要求消息中出现：
- `市场情绪指标（最新交易日）`
- `• 涨幅 >9.5%: 76家`
- `• 跌幅 <-9.5%: 9家`
- `• 炸板率: 34.00%`
- `• 最近3日涨幅>30%: 21家`
- 趋势行包含 `成交额：1.23 万亿`
- 趋势行包含 `<20H>: 210`、`<20L>: 63`、`<60H>: 88`、`<60L>: 42`

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n stock_analysis pytest tests/unit/test_market_close_job.py -k summary_first_and_keeps_trend_lines`
Expected: FAIL，因为当前实现没有 `市场情绪指标（最新交易日）` 分组，趋势行也还未包含尖括号字段。

- [ ] **Step 3: Write minimal implementation**

在 `FeishuNotificationService._build_message()` 中：
- 恢复 `市场情绪指标（最新交易日）` 独立分组
- 把四个情绪指标从摘要/其他分组移到该分组
- 调整趋势行格式为 `成交额：x.xx 万亿，涨停：x，跌停：x，<20H>: x，<20L>: x，<60H>: x，<60L>: x`

- [ ] **Step 4: Run targeted tests**

Run: `conda run -n stock_analysis pytest tests/unit/test_market_close_job.py`
Expected: PASS

- [ ] **Step 5: Run full verification**

Run: `conda run -n stock_analysis pytest`
Expected: PASS with all tests green
