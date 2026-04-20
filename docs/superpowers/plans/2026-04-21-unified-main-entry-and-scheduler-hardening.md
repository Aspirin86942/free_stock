# Unified Main Entry And Scheduler Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 收敛为单入口 `main.py`（子命令分发），并修复盘后调度的交易日语义、幂等发送、稳定性与指标可用性问题。  
**Architecture:** 采用渐进增强策略，先做入口与调度稳定性修复（批次 1），再做指标补齐与降级审计（批次 2）。保持现有模块边界，不做大规模重构。  
**Tech Stack:** Python 3.10+, argparse, APScheduler, Decimal, PyMySQL, pytest

---

## Planned File Structure

**Create**
- `tests/unit/test_main_cli_dispatch.py`
- `tests/unit/test_runtime_scheduler.py`
- `tests/unit/test_market_close_job.py`
- `tests/unit/test_config_runtime_flags.py`

**Modify**
- `main.py`
- `src/gmtrade_live/runtime_scheduler.py`
- `src/gmtrade_live/services/market_close_job.py`
- `src/gmtrade_live/services/feishu_notification_service.py`
- `src/gmtrade_live/services/market_data_sync_service.py`
- `src/gmtrade_live/services/market_breadth_analyzer.py`
- `src/gmtrade_live/services/market_profit_effect_analyzer.py`
- `src/gmtrade_live/services/market_tolerance_analyzer.py`
- `src/gmtrade_live/services/market_emotion_analyzer.py`
- `src/gmtrade_live/services/market_close_report_builder.py`
- `src/gmtrade_live/config.py`
- `config/sim_account.example.yaml`
- `AGENTS.md`
- `docs/market-analysis-runtime.md`

**Delete**
- `scheduler.py`

---

### Task 1: 单入口收敛为 `main.py` 子命令

**Files:**
- Modify: `main.py`
- Delete: `scheduler.py`
- Create: `tests/unit/test_main_cli_dispatch.py`
- Modify: `tests/unit/test_main.py`

- [ ] **Step 1: 编写失败测试，锁定 CLI 分发行为**

```python
def test_main_dispatch_trade(monkeypatch):
    ...

def test_main_dispatch_scheduler(monkeypatch):
    ...

def test_main_reject_legacy_flags():
    ...
```

- [ ] **Step 2: 运行失败测试**

Run: `conda run -n stock_analysis pytest tests/unit/test_main_cli_dispatch.py -q`  
Expected: FAIL（子命令尚未实现）

- [ ] **Step 3: 实现 `main.py` 子命令路由**

```python
subparsers = parser.add_subparsers(dest="command", required=True)
trade_parser = subparsers.add_parser("trade")
scheduler_parser = subparsers.add_parser("scheduler")
```

- [ ] **Step 4: 移除 `scheduler.py`，确保分发只走 `main.py`**

Run: `rg -n "python scheduler.py|scheduler.py --config" docs AGENTS.md`  
Expected: 仅保留迁移说明，不保留作为正式入口

- [ ] **Step 5: 验证通过**

Run: `conda run -n stock_analysis pytest tests/unit/test_main.py tests/unit/test_main_cli_dispatch.py -q`  
Expected: PASS

---

### Task 2: 调度语义修复（交易日完成态 + 重试边界 + trade 占位）

**Files:**
- Modify: `src/gmtrade_live/runtime_scheduler.py`
- Create: `tests/unit/test_runtime_scheduler.py`

- [ ] **Step 1: 编写失败测试**

```python
def test_skip_when_not_trade_day(...):
    ...

def test_retry_only_on_retryable_failure(...):
    ...

def test_trade_enabled_only_warns_unimplemented(...):
    ...
```

- [ ] **Step 2: 运行失败测试**

Run: `conda run -n stock_analysis pytest tests/unit/test_runtime_scheduler.py -q`  
Expected: FAIL

- [ ] **Step 3: 实现调度判定与重试**

```python
if not self._has_completed_trade_day():
    logger.info("skip market close job")
    return
```

- [ ] **Step 4: 验证通过**

Run: `conda run -n stock_analysis pytest tests/unit/test_runtime_scheduler.py -q`  
Expected: PASS

---

### Task 3: 盘后任务幂等与稳定性（空报告保护、连接释放）

**Files:**
- Modify: `src/gmtrade_live/services/market_close_job.py`
- Modify: `src/gmtrade_live/services/feishu_notification_service.py`
- Create: `tests/unit/test_market_close_job.py`

- [ ] **Step 1: 编写失败测试**

```python
def test_market_close_job_uses_finally_to_close_repo(...):
    ...

def test_market_close_job_skip_send_when_already_sent(...):
    ...

def test_feishu_builder_handles_empty_daily_rows(...):
    ...
```

- [ ] **Step 2: 运行失败测试**

Run: `conda run -n stock_analysis pytest tests/unit/test_market_close_job.py -q`  
Expected: FAIL

- [ ] **Step 3: 实现幂等发送 checkpoint 与 finally 释放**

```python
try:
    ...
finally:
    repository.close()
```

- [ ] **Step 4: 实现空报告保护**

```python
if not report.daily_rows:
    return {"msg_type": "text", "content": {"text": "...暂无可展示数据..."}}
```

- [ ] **Step 5: 验证通过**

Run: `conda run -n stock_analysis pytest tests/unit/test_market_close_job.py -q`  
Expected: PASS

---

### Task 4: 配置安全解析（布尔字段）

**Files:**
- Modify: `src/gmtrade_live/config.py`
- Create: `tests/unit/test_config_runtime_flags.py`

- [ ] **Step 1: 编写失败测试，覆盖 `"false"` / `"true"` / `0` / `1`**

```python
def test_parse_enabled_string_false_to_false():
    ...
```

- [ ] **Step 2: 运行失败测试**

Run: `conda run -n stock_analysis pytest tests/unit/test_config_runtime_flags.py -q`  
Expected: FAIL

- [ ] **Step 3: 实现显式布尔解析函数并替换 `bool(...)`**

```python
def _parse_bool(value: Any, field_name: str) -> bool:
    ...
```

- [ ] **Step 4: 验证通过**

Run: `conda run -n stock_analysis pytest tests/unit/test_config_runtime_flags.py tests/unit/test_config.py -q`  
Expected: PASS

---

### Task 5: 指标完善（gm + MySQL 范围内）

**Files:**
- Modify: `src/gmtrade_live/services/market_breadth_analyzer.py`
- Modify: `src/gmtrade_live/services/market_profit_effect_analyzer.py`
- Modify: `src/gmtrade_live/services/market_tolerance_analyzer.py`
- Modify: `src/gmtrade_live/services/market_emotion_analyzer.py`
- Modify: `src/gmtrade_live/services/market_close_report_builder.py`

- [ ] **Step 1: 为可补齐指标添加测试（A/B级）**

```python
def test_breadth_new_high_low_window():
    ...

def test_emotion_three_day_gain_count():
    ...
```

- [ ] **Step 2: 运行失败测试**

Run: `conda run -n stock_analysis pytest tests/unit/test_market_*analyzer*.py -q`  
Expected: FAIL（当前有 TODO/占位）

- [ ] **Step 3: 实现 A/B 级指标，C 级口径显式降级标记**

```python
report = MarketCloseReport(..., data_quality_flags=[...])
```

- [ ] **Step 4: 验证通过**

Run: `conda run -n stock_analysis pytest tests/unit/test_market_* -q`  
Expected: PASS

---

### Task 6: 文档与命令口径更新

**Files:**
- Modify: `docs/market-analysis-runtime.md`
- Modify: `AGENTS.md`
- Modify: `config/sim_account.example.yaml`

- [ ] **Step 1: 更新运行命令为 `main.py` 子命令风格**
- [ ] **Step 2: 统一 `19:15`、`trade默认关闭`、`trade仅占位` 口径**
- [ ] **Step 3: 验证文档无旧入口残留**

Run: `rg -n "python scheduler.py|scheduler.py --config" docs AGENTS.md`  
Expected: 无正式用法残留

---

### Task 7: 全量验证与收尾

**Files:**
- N/A（验证任务）

- [ ] **Step 1: 运行核心单测集**

Run: `conda run -n stock_analysis pytest tests/unit/test_main.py tests/unit/test_main_cli_dispatch.py tests/unit/test_runtime_scheduler.py tests/unit/test_market_close_job.py tests/unit/test_config.py tests/unit/test_config_runtime_flags.py -q`  
Expected: PASS

- [ ] **Step 2: 运行市场分析相关单测**

Run: `conda run -n stock_analysis pytest tests/unit/test_market_* -q`  
Expected: PASS

- [ ] **Step 3: 代码风格检查**

Run: `conda run -n stock_analysis ruff check src tests main.py`  
Expected: All checks passed

- [ ] **Step 4: 变更总结**
- [ ] **Step 5: 按需求执行提交策略（不混入无关改动）**

---

## Self-Review

- [x] 覆盖了 spec 的入口收敛、调度语义、幂等、稳定性、指标完善、文档口径。
- [x] 未包含 TODO/TBD 占位步骤。
- [x] 任务顺序为“先高风险修复，再指标补齐”，与渐进增强策略一致。
