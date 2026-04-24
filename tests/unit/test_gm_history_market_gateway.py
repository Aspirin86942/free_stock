"""掘金历史行情网关测试。"""

import time
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from gmtrade_live.errors import ServiceError
from gmtrade_live.gateways.gm_history_market_gateway import GMHistoryMarketGateway


@pytest.fixture
def mock_api() -> MagicMock:
    return MagicMock()


@pytest.fixture
def gateway(mock_api: MagicMock) -> GMHistoryMarketGateway:
    return GMHistoryMarketGateway(api_module=mock_api)


def test_connect_sets_token_and_endpoint(
    gateway: GMHistoryMarketGateway, mock_api: MagicMock
) -> None:
    """测试连接设置 token 和 endpoint。"""
    gateway.connect("test-token", "127.0.0.1:7001")

    mock_api.set_token.assert_called_once_with("test-token")
    mock_api.set_endpoint.assert_not_called()


def test_get_security_master_filters_by_board(
    gateway: GMHistoryMarketGateway, mock_api: MagicMock
) -> None:
    """测试股票池按板块过滤。"""
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
            "sec_name": "创业板股票",
            "listed_date": "2015-01-01 00:00:00",
        },
        {
            "symbol": "SHSE.600001",
            "exchange": "SHSE",
            "sec_name": "主板股票",
            "listed_date": "2010-01-01 00:00:00",
        },
        {
            "symbol": "SHSE.000001",
            "exchange": "SHSE",
            "sec_name": "指数",
            "listed_date": "2000-01-01 00:00:00",
        },
    ]

    result = gateway.get_security_master("ashare_main_gem_star")

    assert len(result) == 3
    assert result[0].symbol == "SHSE.688001"
    assert result[0].board == "star"
    assert result[1].symbol == "SZSE.300001"
    assert result[1].board == "gem"
    assert result[2].symbol == "SHSE.600001"
    assert result[2].board == "main"


def test_fetch_daily_bars_returns_empty_for_empty_symbols(
    gateway: GMHistoryMarketGateway, mock_api: MagicMock
) -> None:
    """测试空股票列表返回空列表。"""
    result = gateway.fetch_daily_bars([], date(2026, 4, 1), date(2026, 4, 15))

    assert result == []
    mock_api.history.assert_not_called()


def test_fetch_daily_bars_parses_bar_data(
    gateway: GMHistoryMarketGateway, mock_api: MagicMock
) -> None:
    """测试解析日线数据。"""
    mock_api.get_trading_dates.return_value = ["2026-04-15 00:00:00"]
    mock_api.history.return_value = [
        {
            "symbol": "SHSE.600001",
            "eob": "2026-04-15 15:00:00",
            "open": 10.5,
            "high": 11.0,
            "low": 10.2,
            "close": 10.8,
            "pre_close": 10.3,
            "volume": 1000000,
            "amount": 10800000.0,
        }
    ]
    mock_api.stk_get_daily_basic_pt.return_value = [
        {
            "symbol": "SHSE.600001",
            "trade_date": "2026-04-15",
            "turnrate": 12.5,
        }
    ]

    result = gateway.fetch_daily_bars(["SHSE.600001"], date(2026, 4, 15), date(2026, 4, 15))

    assert len(result) == 1
    bar = result[0]
    assert bar.symbol == "SHSE.600001"
    assert bar.trade_date == date(2026, 4, 15)
    assert bar.close == Decimal("10.8")
    assert bar.volume == 1000000
    assert bar.turnover_rate == Decimal("12.5")
    assert bar.has_trade is True
    assert bar.suspended is False


def test_fetch_daily_bars_detects_suspended(
    gateway: GMHistoryMarketGateway, mock_api: MagicMock
) -> None:
    """测试检测停牌。"""
    mock_api.get_trading_dates.return_value = ["2026-04-15 00:00:00"]
    mock_api.history.return_value = [
        {
            "symbol": "SHSE.600001",
            "eob": "2026-04-15 15:00:00",
            "open": 0,
            "high": 0,
            "low": 0,
            "close": 0,
            "pre_close": 10.3,
            "volume": 0,
            "amount": 0,
        }
    ]
    mock_api.stk_get_daily_basic_pt.return_value = []

    result = gateway.fetch_daily_bars(["SHSE.600001"], date(2026, 4, 15), date(2026, 4, 15))

    assert len(result) == 1
    bar = result[0]
    assert bar.suspended is True
    assert bar.has_trade is False


def test_fetch_daily_bars_uses_symbol_mode_for_long_range(
    gateway: GMHistoryMarketGateway, mock_api: MagicMock
) -> None:
    """测试在多交易日场景按股票拉取换手率。"""
    mock_api.get_trading_dates.return_value = [
        "2026-04-14 00:00:00",
        "2026-04-15 00:00:00",
    ]
    mock_api.history.return_value = [
        {
            "symbol": "SHSE.600001",
            "eob": "2026-04-14 15:00:00",
            "open": 10.0,
            "high": 10.2,
            "low": 9.8,
            "close": 10.1,
            "pre_close": 9.9,
            "volume": 100,
            "amount": 1000,
        },
        {
            "symbol": "SHSE.600001",
            "eob": "2026-04-15 15:00:00",
            "open": 10.1,
            "high": 10.3,
            "low": 10.0,
            "close": 10.2,
            "pre_close": 10.1,
            "volume": 120,
            "amount": 1224,
        },
    ]
    mock_api.stk_get_daily_basic.return_value = [
        {"symbol": "SHSE.600001", "trade_date": "2026-04-14", "turnrate": 8.1},
        {"symbol": "SHSE.600001", "trade_date": "2026-04-15", "turnrate": 9.2},
    ]

    result = gateway.fetch_daily_bars(["SHSE.600001"], date(2026, 4, 14), date(2026, 4, 15))

    assert len(result) == 2
    assert result[0].turnover_rate == Decimal("8.1")
    assert result[1].turnover_rate == Decimal("9.2")
    mock_api.stk_get_daily_basic.assert_called_once()
    mock_api.stk_get_daily_basic_pt.assert_not_called()


def test_get_trade_dates_returns_sorted_dates(
    gateway: GMHistoryMarketGateway, mock_api: MagicMock
) -> None:
    """测试返回排序后的交易日列表。"""
    mock_api.get_trading_dates.return_value = [
        "2026-04-11 00:00:00",
        "2026-04-14 00:00:00",
        "2026-04-15 00:00:00",
    ]

    result = gateway.get_trade_dates(date(2026, 4, 11), date(2026, 4, 15))

    assert result == [date(2026, 4, 11), date(2026, 4, 14), date(2026, 4, 15)]


def test_get_trade_dates_raises_timeout_when_api_blocks(
    gateway: GMHistoryMarketGateway,
    mock_api: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """测试交易日接口阻塞时会触发超时错误。"""

    def _slow_get_trading_dates(**_: object) -> list[str]:
        time.sleep(0.05)
        return ["2026-04-15 00:00:00"]

    mock_api.get_trading_dates.side_effect = _slow_get_trading_dates
    monkeypatch.setattr(gateway, "_GET_TRADING_DATES_TIMEOUT_SECONDS", 0.01)

    with pytest.raises(ServiceError) as exc_info:
        gateway.get_trade_dates(date(2026, 4, 11), date(2026, 4, 15))

    assert exc_info.value.code == "gm.fetch_trade_dates_timeout"


def test_get_latest_trade_date_returns_most_recent(
    gateway: GMHistoryMarketGateway, mock_api: MagicMock
) -> None:
    """测试返回最近的交易日。"""
    mock_api.get_trading_dates.return_value = [
        "2026-04-11 00:00:00",
        "2026-04-14 00:00:00",
        "2026-04-15 00:00:00",
    ]

    result = gateway.get_latest_trade_date(date(2026, 4, 16))

    assert result == date(2026, 4, 15)


def test_get_next_trade_date_returns_next(
    gateway: GMHistoryMarketGateway, mock_api: MagicMock
) -> None:
    """测试返回下一个交易日。"""
    mock_api.get_trading_dates.return_value = [
        "2026-04-15 00:00:00",
        "2026-04-16 00:00:00",
        "2026-04-17 00:00:00",
    ]

    result = gateway.get_next_trade_date(date(2026, 4, 15))

    assert result == date(2026, 4, 16)
