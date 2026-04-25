# SZSE 30xxxx GEM Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修正 `SZSE.30xxxx` 的创业板识别规则，并补齐此前因 `301` 未入股票池而漏掉的主数据与历史日线回补路径。

**Architecture:** 先在 `GMHistoryMarketGateway` 收口证券分类口径，把深市 `30` 段统一归为 `gem`。再在 `MarketDataSyncService` 中把股票池刷新前置，并为“本轮新纳入但历史缺失”的 symbol 增加定向历史回补，避免仅靠普通增量同步遗漏旧数据。

**Tech Stack:** Python 3.10+, pytest, unittest.mock, conda (`stock_analysis`), GM API gateway, MySQL repository abstraction

---

## File Structure

- Modify: `src/gmtrade_live/gateways/gm_history_market_gateway.py`
  - 统一 `SZSE.30xxxx -> gem` 的板块识别规则，并更新中文注释说明。
- Modify: `tests/unit/test_gm_history_market_gateway.py`
  - 增加 `301` / `30xxxx` 创业板识别回归测试。
- Modify: `src/gmtrade_live/services/market_data_sync_service.py`
  - 把股票池刷新移动到“无新交易日提前返回”之前。
  - 新增“识别本轮新纳入 symbol”与“定向历史回补”的辅助方法。
  - 保持 checkpoint 只由普通增量同步推进，避免历史回补误推进 checkpoint。
- Modify: `tests/unit/test_market_data_sync_service.py`
  - 更新“无新数据”场景测试口径。
  - 增加“无普通增量窗口也能回补新 symbol 历史”与“新 symbol 历史回补 + 普通增量并存”的回归测试。

## Task 1: 修正创业板识别规则

**Files:**
- Modify: `src/gmtrade_live/gateways/gm_history_market_gateway.py`
- Test: `tests/unit/test_gm_history_market_gateway.py`

- [ ] **Step 1: 写失败测试，锁定 `SZSE.301xxx` 会被漏掉的现状**

```python
def test_get_security_master_treats_szse_30xxxx_as_gem(
    gateway: GMHistoryMarketGateway, mock_api: MagicMock
) -> None:
    """测试深市 30 段股票统一按创业板处理。"""
    mock_api.get_instruments.return_value = [
        {
            "symbol": "SHSE.688001",
            "exchange": "SHSE",
            "sec_name": "科创板股票",
            "listed_date": "2020-01-01 00:00:00",
        },
        {
            "symbol": "SZSE.300001",
            "exchange": "SZSE",
            "sec_name": "创业板 300",
            "listed_date": "2015-01-01 00:00:00",
        },
        {
            "symbol": "SZSE.301001",
            "exchange": "SZSE",
            "sec_name": "创业板 301",
            "listed_date": "2021-01-01 00:00:00",
        },
        {
            "symbol": "SHSE.600001",
            "exchange": "SHSE",
            "sec_name": "主板股票",
            "listed_date": "2010-01-01 00:00:00",
        },
        {
            "symbol": "BJSE.830001",
            "exchange": "BJSE",
            "sec_name": "北交所股票",
            "listed_date": "2020-01-01 00:00:00",
        },
    ]

    result = gateway.get_security_master("ashare_main_gem_star")

    symbol_to_board = {security.symbol: security.board for security in result}
    assert symbol_to_board == {
        "SHSE.688001": "star",
        "SZSE.300001": "gem",
        "SZSE.301001": "gem",
        "SHSE.600001": "main",
    }
```

- [ ] **Step 2: 运行单测，确认它先红**

Run: `conda run -n stock_analysis pytest tests/unit/test_gm_history_market_gateway.py::test_get_security_master_treats_szse_30xxxx_as_gem -v`

Expected: FAIL，断言里缺少 `SZSE.301001`，证明当前实现只识别了 `SZSE.300xxx`。

- [ ] **Step 3: 做最小实现，只扩大深市创业板识别前缀**

```python
def get_security_master(self, scope: str) -> list[SecurityMaster]:
    """获取股票池（沪深主板 + 创业板 + 科创板）。"""
    if scope != "ashare_main_gem_star":
        raise ServiceError(
            code="gm.unsupported_universe",
            message=f"不支持的股票池范围: {scope}",
            retryable=False,
            context={"scope": scope},
        )

    # 掘金 API: get_instruments(exchanges, sec_types, names, fields)
    # 沪深主板: SHSE + SZSE，创业板: SZSE.30xxxx，科创板: SHSE.688xxxx
    try:
        instruments = self._api.get_instruments(
            exchanges="SHSE,SZSE",
            sec_types=[1],
            fields="symbol,exchange,sec_name,listed_date",
        )
    except Exception as exc:
        raise ServiceError(
            code="gm.fetch_instruments_failed",
            message=f"获取股票池失败: {exc}",
            retryable=True,
            context={},
        ) from exc

    results: list[SecurityMaster] = []
    for inst in instruments:
        symbol = str(inst["symbol"])
        exchange = str(inst["exchange"])
        name = str(inst["sec_name"])
        listed_date_str = str(inst["listed_date"])

        # 为什么这里统一用 SZSE.30 前缀：
        # 这次修复的目标是把深市 30 段股票整体纳入创业板，而不是继续为 301 单独打补丁。
        if symbol.startswith("SHSE.688"):
            board = "star"
        elif symbol.startswith("SZSE.30"):
            board = "gem"
        elif symbol.startswith("SHSE.6") or symbol.startswith("SZSE.0"):
            board = "main"
        else:
            continue

        listed_date = date.fromisoformat(listed_date_str.split()[0])
        results.append(
            SecurityMaster(
                symbol=symbol,
                exchange=exchange,
                name=name,
                board=board,
                listed_date=listed_date,
            )
        )

    return results
```

- [ ] **Step 4: 运行网关测试文件，确认没有回归**

Run: `conda run -n stock_analysis pytest tests/unit/test_gm_history_market_gateway.py -q`

Expected: PASS

- [ ] **Step 5: 提交这一小步**

```bash
git add tests/unit/test_gm_history_market_gateway.py src/gmtrade_live/gateways/gm_history_market_gateway.py
git commit -m "fix: treat SZSE 30xxxx as GEM board"
```

## Task 2: 无普通增量窗口时仍刷新股票池并回补新 symbol 历史

**Files:**
- Modify: `tests/unit/test_market_data_sync_service.py`
- Modify: `src/gmtrade_live/services/market_data_sync_service.py`

- [ ] **Step 1: 先改测试，锁定“无新交易日”新口径**

```python
def test_sync_returns_zero_when_no_new_data(
    service: MarketDataSyncService,
    mock_gateway: MagicMock,
    mock_repository: MagicMock,
) -> None:
    """测试无普通增量时仍会刷新股票池，但没有新 symbol 时返回零。"""
    securities = [
        SecurityMaster(
            symbol="SHSE.600001",
            exchange="SHSE",
            name="测试股票",
            board="main",
            listed_date=date(2020, 1, 1),
        )
    ]
    mock_repository.get_last_success_trade_date.return_value = date(2026, 4, 16)
    mock_repository.get_latest_trade_date_in_daily_bar.return_value = date(2026, 4, 16)
    mock_repository.get_all_symbols.return_value = ["SHSE.600001"]
    mock_repository.get_trade_dates_with_missing_turnover.return_value = []
    mock_gateway.get_next_trade_date.return_value = date(2026, 4, 17)
    mock_gateway.get_latest_trade_date.return_value = date(2026, 4, 16)
    mock_gateway.get_security_master.return_value = securities

    result = service.sync()

    assert result.inserted_rows == 0
    assert result.latest_trade_date == date(2026, 4, 16)
    mock_gateway.get_security_master.assert_called_once_with("ashare_main_gem_star")
    mock_repository.upsert_security_master.assert_called_once_with(securities)
    mock_repository.upsert_daily_bars.assert_not_called()


def test_sync_repairs_recent_turnover_when_no_new_data(
    service: MarketDataSyncService,
    mock_gateway: MagicMock,
    mock_repository: MagicMock,
) -> None:
    """测试无新增交易日时会先刷新股票池，再执行近期换手率修复。"""
    securities = [
        SecurityMaster(
            symbol="SHSE.600001",
            exchange="SHSE",
            name="测试股票",
            board="main",
            listed_date=date(2020, 1, 1),
        )
    ]
    mock_repository.get_last_success_trade_date.return_value = date(2026, 4, 16)
    mock_repository.get_latest_trade_date_in_daily_bar.return_value = date(2026, 4, 16)
    mock_repository.get_trade_dates_with_missing_turnover.return_value = [
        date(2026, 4, 15),
        date(2026, 4, 16),
    ]
    mock_repository.get_all_symbols.side_effect = [
        ["SHSE.600001"],
        ["SHSE.600001"],
    ]
    mock_gateway.get_next_trade_date.return_value = date(2026, 4, 17)
    mock_gateway.get_latest_trade_date.return_value = date(2026, 4, 16)
    mock_gateway.get_security_master.return_value = securities
    mock_gateway.fetch_daily_bars.return_value = [
        DailyBar(
            symbol="SHSE.600001",
            trade_date=date(2026, 4, 16),
            open=Decimal("10"),
            high=Decimal("10.5"),
            low=Decimal("9.8"),
            close=Decimal("10.2"),
            pre_close=Decimal("10"),
            volume=1000,
            amount=Decimal("10000"),
            turnover_rate=Decimal("8.8"),
            is_st=False,
            suspended=False,
            has_trade=True,
        )
    ]
    mock_repository.upsert_daily_bars.return_value = 1

    result = service.sync()

    assert result.inserted_rows == 1
    mock_repository.upsert_security_master.assert_called_once_with(securities)
    mock_gateway.fetch_daily_bars.assert_called_once_with(
        ["SHSE.600001"],
        date(2026, 4, 15),
        date(2026, 4, 16),
    )
    mock_repository.upsert_daily_bars.assert_called_once()


def test_sync_backfills_new_symbols_even_when_no_incremental_window(
    service: MarketDataSyncService,
    mock_gateway: MagicMock,
    mock_repository: MagicMock,
) -> None:
    """测试没有新交易日时，仍会回补新纳入 symbol 的历史数据。"""
    securities = [
        SecurityMaster(
            symbol="SHSE.600001",
            exchange="SHSE",
            name="老股票",
            board="main",
            listed_date=date(2020, 1, 1),
        ),
        SecurityMaster(
            symbol="SZSE.301001",
            exchange="SZSE",
            name="新纳入创业板",
            board="gem",
            listed_date=date(2021, 1, 1),
        ),
    ]
    mock_repository.get_last_success_trade_date.return_value = date(2026, 4, 16)
    mock_repository.get_latest_trade_date_in_daily_bar.return_value = date(2026, 4, 16)
    mock_repository.get_all_symbols.return_value = ["SHSE.600001"]
    mock_gateway.get_next_trade_date.return_value = date(2026, 4, 17)
    mock_gateway.get_latest_trade_date.return_value = date(2026, 4, 16)
    mock_gateway.get_trade_date_n_years_ago.return_value = date(2023, 4, 16)
    mock_gateway.get_security_master.return_value = securities
    mock_gateway.fetch_daily_bars.return_value = [
        DailyBar(
            symbol="SZSE.301001",
            trade_date=date(2026, 4, 16),
            open=Decimal("10"),
            high=Decimal("10.5"),
            low=Decimal("9.8"),
            close=Decimal("10.2"),
            pre_close=Decimal("10"),
            volume=1000,
            amount=Decimal("10000"),
            turnover_rate=None,
            is_st=False,
            suspended=False,
            has_trade=True,
        )
    ]
    mock_repository.upsert_daily_bars.return_value = 1

    result = service.sync()

    assert result.inserted_rows == 1
    assert result.latest_trade_date == date(2026, 4, 16)
    mock_repository.upsert_security_master.assert_called_once_with(securities)
    mock_gateway.fetch_daily_bars.assert_called_once_with(
        ["SZSE.301001"],
        date(2023, 4, 16),
        date(2026, 4, 16),
    )
    mock_repository.save_last_success_trade_date.assert_not_called()
```

- [ ] **Step 2: 运行这两个测试，确认它们先红**

Run: `conda run -n stock_analysis pytest tests/unit/test_market_data_sync_service.py::test_sync_returns_zero_when_no_new_data tests/unit/test_market_data_sync_service.py::test_sync_backfills_new_symbols_even_when_no_incremental_window -v`

Expected: FAIL，当前实现会在 `start_date > end_date` 时提前返回，既不会刷新股票池，也不会触发 `SZSE.301001` 的历史回补。

- [ ] **Step 3: 做最小实现，先把股票池刷新前置，再为新 symbol 增加历史回补 helper**

```python
class MarketDataSyncService:
    """市场数据同步服务。"""

    _TURNOVER_REPAIR_TRADE_DAYS = 2
    _SYNC_BATCH_SIZE = 50

    def sync(self) -> SyncResult:
        last_success_date = self.repository.get_last_success_trade_date("market_daily_sync")
        latest_trade_date_in_db = self.repository.get_latest_trade_date_in_daily_bar()

        effective_last_success_date = last_success_date
        if (
            last_success_date is not None
            and latest_trade_date_in_db is not None
            and last_success_date > latest_trade_date_in_db
        ):
            effective_last_success_date = latest_trade_date_in_db
            self.repository.save_last_success_trade_date(
                "market_daily_sync",
                latest_trade_date_in_db,
            )
        elif last_success_date is not None and latest_trade_date_in_db is None:
            effective_last_success_date = None

        if effective_last_success_date is None:
            start_date = self.gateway.get_trade_date_n_years_ago(self.config.history_years)
            is_first_sync = True
        else:
            start_date = self.gateway.get_next_trade_date(effective_last_success_date)
            is_first_sync = False

        end_date = self.gateway.get_latest_trade_date()

        securities = self.gateway.get_security_master(self.config.universe)
        existing_symbols = set(self.repository.get_all_symbols())
        self.repository.upsert_security_master(securities)

        symbols = [security.symbol for security in securities]
        new_symbols = [symbol for symbol in symbols if symbol not in existing_symbols]
        backfilled_rows = self._backfill_new_symbols(new_symbols, end_date)

        if start_date > end_date:
            if new_symbols:
                return SyncResult(
                    latest_trade_date=effective_last_success_date
                    or latest_trade_date_in_db
                    or end_date,
                    inserted_rows=backfilled_rows,
                    updated_rows=0,
                    is_first_sync=is_first_sync,
                )

            repaired_rows = self._repair_recent_turnover_rates(
                latest_trade_date=latest_trade_date_in_db
                or effective_last_success_date
                or end_date
            )
            return SyncResult(
                latest_trade_date=effective_last_success_date
                or latest_trade_date_in_db
                or end_date,
                inserted_rows=backfilled_rows + repaired_rows,
                updated_rows=0,
                is_first_sync=is_first_sync,
            )

        incremental_rows, latest_incremental_trade_date = self._sync_symbol_batches(
            symbols,
            start_date,
            end_date,
        )

        if latest_incremental_trade_date is not None and (
            effective_last_success_date is None
            or latest_incremental_trade_date > effective_last_success_date
        ):
            self.repository.save_last_success_trade_date(
                "market_daily_sync",
                latest_incremental_trade_date,
            )

        return SyncResult(
            latest_trade_date=latest_incremental_trade_date
            or latest_trade_date_in_db
            or end_date,
            inserted_rows=backfilled_rows + incremental_rows,
            updated_rows=0,
            is_first_sync=is_first_sync,
        )

    def _backfill_new_symbols(self, symbols: list[str], end_date: date) -> int:
        """对本轮新纳入的证券执行定向历史回补。"""
        if not symbols:
            return 0

        start_date = self.gateway.get_trade_date_n_years_ago(self.config.history_years)
        affected_rows, _ = self._sync_symbol_batches(symbols, start_date, end_date)
        return affected_rows

    def _sync_symbol_batches(
        self,
        symbols: list[str],
        start_date: date,
        end_date: date,
    ) -> tuple[int, date | None]:
        """按固定批次同步一组 symbol 的日线数据。"""
        if not symbols or start_date > end_date:
            return 0, None

        total_affected = 0
        latest_synced_trade_date: date | None = None

        for i in range(0, len(symbols), self._SYNC_BATCH_SIZE):
            batch_symbols = symbols[i : i + self._SYNC_BATCH_SIZE]
            bars = self.gateway.fetch_daily_bars(batch_symbols, start_date, end_date)
            if not bars:
                continue

            affected = self.repository.upsert_daily_bars(bars)
            total_affected += affected
            batch_latest_trade_date = max(bar.trade_date for bar in bars)
            if (
                latest_synced_trade_date is None
                or batch_latest_trade_date > latest_synced_trade_date
            ):
                latest_synced_trade_date = batch_latest_trade_date

        return total_affected, latest_synced_trade_date
```

- [ ] **Step 4: 运行同步服务测试文件，确认无新交易日语义已经转绿**

Run: `conda run -n stock_analysis pytest tests/unit/test_market_data_sync_service.py -q`

Expected: PASS，尤其是：
- `test_sync_returns_zero_when_no_new_data`
- `test_sync_backfills_new_symbols_even_when_no_incremental_window`
- `test_sync_repairs_recent_turnover_when_no_new_data`

- [ ] **Step 5: 提交这一小步**

```bash
git add tests/unit/test_market_data_sync_service.py src/gmtrade_live/services/market_data_sync_service.py
git commit -m "feat: backfill newly discovered market symbols"
```

## Task 3: 新 symbol 历史回补与普通增量并存时保持顺序和 checkpoint 语义

**Files:**
- Modify: `tests/unit/test_market_data_sync_service.py`
- Modify: `src/gmtrade_live/services/market_data_sync_service.py`

- [ ] **Step 1: 再写一个失败测试，锁定“先回补新 symbol，再跑普通增量”**

```python
from unittest.mock import MagicMock, call


def test_sync_backfills_new_symbols_before_incremental_sync(
    service: MarketDataSyncService,
    mock_gateway: MagicMock,
    mock_repository: MagicMock,
) -> None:
    """测试新纳入 symbol 会先走历史回补，再走普通增量。"""
    securities = [
        SecurityMaster(
            symbol="SHSE.600001",
            exchange="SHSE",
            name="老股票",
            board="main",
            listed_date=date(2020, 1, 1),
        ),
        SecurityMaster(
            symbol="SZSE.301001",
            exchange="SZSE",
            name="新纳入创业板",
            board="gem",
            listed_date=date(2021, 1, 1),
        ),
    ]
    mock_repository.get_last_success_trade_date.return_value = date(2026, 4, 15)
    mock_repository.get_latest_trade_date_in_daily_bar.return_value = date(2026, 4, 15)
    mock_repository.get_all_symbols.return_value = ["SHSE.600001"]
    mock_gateway.get_next_trade_date.return_value = date(2026, 4, 16)
    mock_gateway.get_latest_trade_date.return_value = date(2026, 4, 16)
    mock_gateway.get_trade_date_n_years_ago.return_value = date(2023, 4, 16)
    mock_gateway.get_security_master.return_value = securities
    mock_gateway.fetch_daily_bars.side_effect = [
        [
            DailyBar(
                symbol="SZSE.301001",
                trade_date=date(2026, 4, 16),
                open=Decimal("10"),
                high=Decimal("10.5"),
                low=Decimal("9.8"),
                close=Decimal("10.2"),
                pre_close=Decimal("10"),
                volume=1000,
                amount=Decimal("10000"),
                turnover_rate=None,
                is_st=False,
                suspended=False,
                has_trade=True,
            )
        ],
        [
            DailyBar(
                symbol="SHSE.600001",
                trade_date=date(2026, 4, 16),
                open=Decimal("10"),
                high=Decimal("10.5"),
                low=Decimal("9.8"),
                close=Decimal("10.2"),
                pre_close=Decimal("10"),
                volume=1000,
                amount=Decimal("10000"),
                turnover_rate=None,
                is_st=False,
                suspended=False,
                has_trade=True,
            ),
            DailyBar(
                symbol="SZSE.301001",
                trade_date=date(2026, 4, 16),
                open=Decimal("10"),
                high=Decimal("10.5"),
                low=Decimal("9.8"),
                close=Decimal("10.2"),
                pre_close=Decimal("10"),
                volume=1000,
                amount=Decimal("10000"),
                turnover_rate=None,
                is_st=False,
                suspended=False,
                has_trade=True,
            ),
        ],
    ]
    mock_repository.upsert_daily_bars.side_effect = [1, 2]

    result = service.sync()

    assert result.inserted_rows == 3
    assert result.latest_trade_date == date(2026, 4, 16)
    assert mock_gateway.fetch_daily_bars.call_args_list == [
        call(["SZSE.301001"], date(2023, 4, 16), date(2026, 4, 16)),
        call(["SHSE.600001", "SZSE.301001"], date(2026, 4, 16), date(2026, 4, 16)),
    ]
    mock_repository.save_last_success_trade_date.assert_called_once_with(
        "market_daily_sync",
        date(2026, 4, 16),
    )
```

- [ ] **Step 2: 跑这个测试，确认它先红**

Run: `conda run -n stock_analysis pytest tests/unit/test_market_data_sync_service.py::test_sync_backfills_new_symbols_before_incremental_sync -v`

Expected: FAIL，若当前实现顺序错误或 checkpoint 混用了历史回补结果，断言会直接暴露出来。

- [ ] **Step 3: 只补最小实现，明确把“历史回补结果”和“普通增量最新交易日”分开管理**

```python
def sync(self) -> SyncResult:
    last_success_date = self.repository.get_last_success_trade_date("market_daily_sync")
    latest_trade_date_in_db = self.repository.get_latest_trade_date_in_daily_bar()

    effective_last_success_date = last_success_date
    if (
        last_success_date is not None
        and latest_trade_date_in_db is not None
        and last_success_date > latest_trade_date_in_db
    ):
        effective_last_success_date = latest_trade_date_in_db
        self.repository.save_last_success_trade_date(
            "market_daily_sync",
            latest_trade_date_in_db,
        )
    elif last_success_date is not None and latest_trade_date_in_db is None:
        effective_last_success_date = None

    if effective_last_success_date is None:
        start_date = self.gateway.get_trade_date_n_years_ago(self.config.history_years)
        is_first_sync = True
    else:
        start_date = self.gateway.get_next_trade_date(effective_last_success_date)
        is_first_sync = False

    end_date = self.gateway.get_latest_trade_date()
    securities = self.gateway.get_security_master(self.config.universe)
    existing_symbols = set(self.repository.get_all_symbols())
    self.repository.upsert_security_master(securities)

    symbols = [security.symbol for security in securities]
    new_symbols = [symbol for symbol in symbols if symbol not in existing_symbols]
    backfilled_rows = self._backfill_new_symbols(new_symbols, end_date)

    incremental_rows = 0
    latest_incremental_trade_date: date | None = None
    if start_date <= end_date:
        incremental_rows, latest_incremental_trade_date = self._sync_symbol_batches(
            symbols,
            start_date,
            end_date,
        )

    if latest_incremental_trade_date is not None and (
        effective_last_success_date is None
        or latest_incremental_trade_date > effective_last_success_date
    ):
        self.repository.save_last_success_trade_date(
            "market_daily_sync",
            latest_incremental_trade_date,
        )

    if start_date > end_date and not new_symbols:
        repaired_rows = self._repair_recent_turnover_rates(
            latest_trade_date=latest_trade_date_in_db
            or effective_last_success_date
            or end_date
        )
    else:
        repaired_rows = 0

    return SyncResult(
        latest_trade_date=latest_incremental_trade_date
        or latest_trade_date_in_db
        or end_date,
        inserted_rows=backfilled_rows + incremental_rows + repaired_rows,
        updated_rows=0,
        is_first_sync=is_first_sync,
    )
```

- [ ] **Step 4: 跑两个测试文件做回归确认**

Run: `conda run -n stock_analysis pytest tests/unit/test_gm_history_market_gateway.py tests/unit/test_market_data_sync_service.py -q`

Expected: PASS

- [ ] **Step 5: 提交这一小步**

```bash
git add tests/unit/test_market_data_sync_service.py src/gmtrade_live/services/market_data_sync_service.py
git commit -m "fix: sync new market symbols before incremental window"
```
