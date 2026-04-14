# Debug M0/M1 Tools Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move M0/M1 connectivity and manual trade capabilities into `tools/debug`, remove old stage service modules, and keep outputs/exit codes stable.

**Architecture:** Introduce two debug scripts that encapsulate M0/M1 logic and expose both script and module execution. Remove `app_runner` dependencies on old services and delete those service modules and their tests.

**Tech Stack:** Python 3.10+, pytest, gmtrade_live gateways/config/models

---

### Task 1: Add failing tests for new debug payload builders

**Files:**
- Create: `D:/Program_python/free_stock/.worktrees/codex-auto-sell-productization/tests/debug/test_check_connectivity.py`
- Create: `D:/Program_python/free_stock/.worktrees/codex-auto-sell-productization/tests/debug/test_manual_trade.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/debug/test_check_connectivity.py
from decimal import Decimal
from datetime import datetime
from zoneinfo import ZoneInfo

from gmtrade_live.models import CashSnapshot, ConnectivityReport, PositionSnapshot, QuoteSnapshot
from tools.debug.check_connectivity import build_connectivity_summary


def test_build_connectivity_summary_returns_payload() -> None:
    report = ConnectivityReport(
        account_id="demo-account",
        session_state="trading",
        cash=CashSnapshot(
            account_id="demo-account",
            available_cash=Decimal("100.00"),
            market_value=Decimal("200.00"),
            total_asset=Decimal("300.00"),
            update_time=datetime(2026, 4, 10, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
        ),
        positions=(
            PositionSnapshot(
                symbol="SHSE.600000",
                exchange="SHSE",
                volume=100,
                available_volume=100,
                cost_price=Decimal("10.00"),
                last_update_time=datetime(2026, 4, 10, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
            ),
        ),
        quotes=(
            QuoteSnapshot(
                symbol="SHSE.600000",
                last_price=Decimal("10.10"),
                quote_time=datetime(2026, 4, 10, 9, 31, tzinfo=ZoneInfo("Asia/Shanghai")),
                source="gm.current",
            ),
        ),
    )

    payload = build_connectivity_summary(report)

    assert payload["account_id"] == "demo-account"
    assert payload["position_count"] == 1
    assert payload["quote_count"] == 1
```

```python
# tests/debug/test_manual_trade.py
from decimal import Decimal
from types import SimpleNamespace

from tools.debug.manual_trade import build_manual_trade_payload


def test_build_manual_trade_payload_maps_fields() -> None:
    report = SimpleNamespace(
        verification_passed=True,
        side="sell",
        cl_ord_id="ORDER_1",
        broker_order_id="BROKER_1",
        submit_accepted=True,
        order_status_confirmed=True,
        execution_status_confirmed=True,
        last_order_status="filled",
        rejection_reason=None,
        filled_volume=100,
        avg_price=Decimal("10.450"),
        message="交易状态已确认",
    )

    payload = build_manual_trade_payload(report)

    assert payload["verification_passed"] is True
    assert payload["cl_ord_id"] == "ORDER_1"
    assert payload["avg_price"] == "10.450"
```

- [ ] **Step 2: Run tests to verify red**

Run: `conda run -n stock_analysis pytest tests/debug/test_check_connectivity.py tests/debug/test_manual_trade.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'tools.debug'`

---

### Task 2: Implement debug scripts and package init

**Files:**
- Create: `D:/Program_python/free_stock/.worktrees/codex-auto-sell-productization/tools/__init__.py`
- Create: `D:/Program_python/free_stock/.worktrees/codex-auto-sell-productization/tools/debug/__init__.py`
- Create: `D:/Program_python/free_stock/.worktrees/codex-auto-sell-productization/tools/debug/check_connectivity.py`
- Create: `D:/Program_python/free_stock/.worktrees/codex-auto-sell-productization/tools/debug/manual_trade.py`

- [ ] **Step 1: Write minimal implementation**

```python
# tools/debug/check_connectivity.py
from __future__ import annotations

import argparse
import json
from pathlib import Path

from gmtrade_live.config import load_config
from gmtrade_live.gateways.gm_market_gateway import GMCurrentQuoteGateway
from gmtrade_live.gateways.gmtrade_trade_gateway import GMTradeGateway
from gmtrade_live.logging_setup import setup_logging
from gmtrade_live.session import resolve_trading_session


def build_connectivity_summary(report) -> dict[str, object]:
    return {
        "account_id": report.account_id,
        "session_state": report.session_state,
        "available_cash": str(report.cash.available_cash),
        "position_count": len(report.positions),
        "quote_count": len(report.quotes),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)

    config = load_config(Path(args.config))
    logger = setup_logging(config.strategy_name, config.log_dir)
    session_state = resolve_trading_session(...)

    gateway = GMTradeGateway()
    market_gateway = GMCurrentQuoteGateway()
    gateway.connect(config)
    market_gateway.connect(config.token)
    cash = gateway.get_cash(config.account_id)
    positions = gateway.get_positions(config.account_id)
    symbols = [item.symbol for item in positions if item.available_volume > 0]
    quotes = market_gateway.get_quotes(symbols)

    report = ...
    print(json.dumps(build_connectivity_summary(report), ensure_ascii=False))
    return 0
```

```python
# tools/debug/manual_trade.py
from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path

from gmtrade_live.config import load_config
from gmtrade_live.logging_setup import setup_logging
from gmtrade_live.session import resolve_trading_session
from gmtrade_live.gateways.gmtrade_trade_gateway import GMTradeGateway


def build_manual_trade_payload(report) -> dict[str, object]:
    return {
        "verification_passed": report.verification_passed,
        "side": report.side,
        "cl_ord_id": report.cl_ord_id,
        "broker_order_id": report.broker_order_id,
        "submit_accepted": report.submit_accepted,
        "order_status_confirmed": report.order_status_confirmed,
        "execution_status_confirmed": report.execution_status_confirmed,
        "last_order_status": report.last_order_status,
        "rejection_reason": report.rejection_reason,
        "filled_volume": report.filled_volume,
        "avg_price": str(report.avg_price) if report.avg_price is not None else None,
        "message": report.message,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--volume", type=int, required=True)
    parser.add_argument("--price-type", required=True)
    parser.add_argument("--price", type=Decimal)
    parser.add_argument("--timeout-seconds", type=int, required=True)
    parser.add_argument("--side", required=True)
    args = parser.parse_args(argv)

    config = load_config(Path(args.config))
    resolve_trading_session(...)
    logger = setup_logging(config.strategy_name, config.log_dir)
    gateway = GMTradeGateway(account_id=config.account_id)
    gateway.connect(config)
    service = ManualTradeService(...)
    report = service.run(...)
    print(json.dumps(build_manual_trade_payload(report), ensure_ascii=False))
    return 0 if report.verification_passed else 1
```

- [ ] **Step 2: Run tests to verify green**

Run: `conda run -n stock_analysis pytest tests/debug/test_check_connectivity.py tests/debug/test_manual_trade.py -q`

Expected: PASS

---

### Task 3: Remove old service modules and adjust app_runner + tests

**Files:**
- Delete: `D:/Program_python/free_stock/.worktrees/codex-auto-sell-productization/src/gmtrade_live/services/m0_connectivity.py`
- Delete: `D:/Program_python/free_stock/.worktrees/codex-auto-sell-productization/src/gmtrade_live/services/m1_manual_trade.py`
- Delete: `D:/Program_python/free_stock/.worktrees/codex-auto-sell-productization/tests/unit/test_m1_manual_trade.py`
- Delete: `D:/Program_python/free_stock/.worktrees/codex-auto-sell-productization/tests/integration/test_m0_connectivity_service.py`
- Delete: `D:/Program_python/free_stock/.worktrees/codex-auto-sell-productization/tests/integration/test_m1_manual_trade_service.py`
- Modify: `D:/Program_python/free_stock/.worktrees/codex-auto-sell-productization/src/gmtrade_live/app_runner.py`
- Modify: `D:/Program_python/free_stock/.worktrees/codex-auto-sell-productization/tests/unit/test_app_runner.py`

- [ ] **Step 1: Update app_runner to remove M0/M1 entry points**

```python
# Remove imports of ConnectivityCheckService and ManualTradeService
# Delete run_m0_connectivity_check and run_m1_manual_trade functions
```

- [ ] **Step 2: Update unit tests to remove M1 assertions**

```python
# Remove tests that exercise run_m1_manual_trade and ServiceError for session mode
```

- [ ] **Step 3: Run targeted unit tests**

Run: `conda run -n stock_analysis pytest tests/unit/test_app_runner.py -q`

Expected: PASS

---

### Task 4: Verify dependencies and full green set, then commit

**Files:**
- Modify: `D:/Program_python/free_stock/.worktrees/codex-auto-sell-productization/main.py` (only if needed by dependency scan)
- Modify: `D:/Program_python/free_stock/.worktrees/codex-auto-sell-productization/observe_decisions.py` (only if needed by dependency scan)

- [ ] **Step 1: Dependency scan**

Run: `rg -n -- "m0_connectivity|m1_manual_trade|ConnectivityCheckService|ManualTradeService" src/gmtrade_live/app_runner.py main.py observe_decisions.py`

Expected: no matches for removed modules/classes

- [ ] **Step 2: Full green command**

Run: `conda run -n stock_analysis pytest tests/debug/test_check_connectivity.py tests/debug/test_manual_trade.py tests/unit/test_main.py tests/unit/test_app_runner.py -q`

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tools tests src/gmtrade_live/app_runner.py
git rm src/gmtrade_live/services/m0_connectivity.py src/gmtrade_live/services/m1_manual_trade.py \
  tests/unit/test_m1_manual_trade.py tests/integration/test_m0_connectivity_service.py \
  tests/integration/test_m1_manual_trade_service.py
git commit -m "refactor(debug): move connectivity and manual trade to tools"
```
