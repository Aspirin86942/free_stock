"""市场数据同步服务测试。"""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, call

import pytest

from gmtrade_live.config import MarketAnalysisConfig
from gmtrade_live.gateways.gm_history_market_gateway import GMHistoryMarketGateway
from gmtrade_live.market_models import DailyBar, SecurityMaster
from gmtrade_live.repositories.mysql_market_repository import MySQLMarketRepository
from gmtrade_live.services.market_data_sync_service import MarketDataSyncService


@pytest.fixture
def config() -> MarketAnalysisConfig:
    return MarketAnalysisConfig(
        enabled=True,
        universe="ashare_main_gem_star",
        history_years=3,
        recent_trade_days=10,
        report_time="19:15",
    )


@pytest.fixture
def mock_gateway() -> MagicMock:
    return MagicMock(spec=GMHistoryMarketGateway)


@pytest.fixture
def mock_repository() -> MagicMock:
    repository = MagicMock(spec=MySQLMarketRepository)
    repository.get_latest_trade_date_in_daily_bar.return_value = None
    repository.get_trade_dates_with_missing_turnover.return_value = []
    repository.get_all_symbols.return_value = []
    return repository


@pytest.fixture
def service(
    config: MarketAnalysisConfig,
    mock_gateway: MagicMock,
    mock_repository: MagicMock,
) -> MarketDataSyncService:
    return MarketDataSyncService(config, mock_gateway, mock_repository)


def test_sync_first_time_fetches_3_years_data(
    service: MarketDataSyncService,
    mock_gateway: MagicMock,
    mock_repository: MagicMock,
) -> None:
    """测试首次同步回补三年数据。"""
    # 模拟首次同步（checkpoint 不存在）
    mock_repository.get_last_success_trade_date.return_value = None
    mock_gateway.get_trade_date_n_years_ago.return_value = date(2023, 4, 16)
    mock_gateway.get_latest_trade_date.return_value = date(2026, 4, 16)
    mock_gateway.get_security_master.return_value = [
        SecurityMaster(
            symbol="SHSE.600001",
            exchange="SHSE",
            name="测试股票",
            board="main",
            listed_date=date(2020, 1, 1),
        )
    ]
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
            turnover_rate=None,
            is_st=False,
            suspended=False,
            has_trade=True,
        )
    ]
    mock_repository.upsert_daily_bars.return_value = 100

    result = service.sync()

    assert result.is_first_sync is True
    assert result.latest_trade_date == date(2026, 4, 16)
    mock_gateway.get_trade_date_n_years_ago.assert_called_once_with(3)
    mock_repository.save_last_success_trade_date.assert_called_once_with(
        "market_daily_sync", date(2026, 4, 16)
    )


def test_sync_incremental_fetches_from_last_checkpoint(
    service: MarketDataSyncService,
    mock_gateway: MagicMock,
    mock_repository: MagicMock,
) -> None:
    """测试增量同步从上次 checkpoint 开始。"""
    # 模拟增量同步（checkpoint 存在）
    mock_repository.get_last_success_trade_date.return_value = date(2026, 4, 15)
    mock_repository.get_latest_trade_date_in_daily_bar.return_value = date(2026, 4, 15)
    mock_gateway.get_next_trade_date.return_value = date(2026, 4, 16)
    mock_gateway.get_latest_trade_date.return_value = date(2026, 4, 16)
    mock_gateway.get_security_master.return_value = [
        SecurityMaster(
            symbol="SHSE.600001",
            exchange="SHSE",
            name="测试股票",
            board="main",
            listed_date=date(2020, 1, 1),
        )
    ]
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
            turnover_rate=None,
            is_st=False,
            suspended=False,
            has_trade=True,
        )
    ]
    mock_repository.upsert_daily_bars.return_value = 10

    result = service.sync()

    assert result.is_first_sync is False
    assert result.latest_trade_date == date(2026, 4, 16)
    mock_gateway.get_next_trade_date.assert_called_once_with(date(2026, 4, 15))
    mock_repository.save_last_success_trade_date.assert_called_once_with(
        "market_daily_sync", date(2026, 4, 16)
    )


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
    mock_gateway.get_next_trade_date.return_value = date(2026, 4, 17)
    mock_gateway.get_latest_trade_date.return_value = date(2026, 4, 16)
    mock_repository.get_trade_dates_with_missing_turnover.return_value = []
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
                trade_date=date(2026, 4, 15),
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
    assert max(
        bar.trade_date
        for bar in mock_repository.upsert_daily_bars.call_args_list[0].args[0]
    ) == date(2026, 4, 15)
    assert max(
        bar.trade_date
        for bar in mock_repository.upsert_daily_bars.call_args_list[1].args[0]
    ) == date(2026, 4, 16)
    mock_repository.save_last_success_trade_date.assert_called_once_with(
        "market_daily_sync",
        date(2026, 4, 16),
    )


def test_sync_batches_symbols_in_chunks(
    service: MarketDataSyncService,
    mock_gateway: MagicMock,
    mock_repository: MagicMock,
) -> None:
    """测试按批次同步股票。"""
    # 模拟 100 只股票，应该分成 2 批（每批 50）
    securities = [
        SecurityMaster(
            symbol=f"SHSE.60{i:04d}",
            exchange="SHSE",
            name=f"股票{i}",
            board="main",
            listed_date=date(2020, 1, 1),
        )
        for i in range(100)
    ]

    mock_repository.get_last_success_trade_date.return_value = None
    mock_gateway.get_trade_date_n_years_ago.return_value = date(2023, 4, 16)
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
            turnover_rate=None,
            is_st=False,
            suspended=False,
            has_trade=True,
        )
    ]
    mock_repository.upsert_daily_bars.return_value = 50

    service.sync()

    # 应该调用 2 次 fetch_daily_bars（100 只股票 / 50 = 2 批）
    assert mock_gateway.fetch_daily_bars.call_count == 2


def test_sync_checkpoint_clamps_to_latest_synced_bar_date(
    service: MarketDataSyncService,
    mock_gateway: MagicMock,
    mock_repository: MagicMock,
) -> None:
    """测试 checkpoint 只推进到实际同步到的最新交易日。"""
    mock_repository.get_last_success_trade_date.return_value = date(2026, 4, 16)
    mock_repository.get_latest_trade_date_in_daily_bar.return_value = date(2026, 4, 16)
    mock_gateway.get_next_trade_date.return_value = date(2026, 4, 17)
    mock_gateway.get_latest_trade_date.return_value = date(2026, 4, 21)
    mock_gateway.get_security_master.return_value = [
        SecurityMaster(
            symbol="SHSE.600001",
            exchange="SHSE",
            name="测试股票",
            board="main",
            listed_date=date(2020, 1, 1),
        )
    ]
    mock_gateway.fetch_daily_bars.return_value = [
        DailyBar(
            symbol="SHSE.600001",
            trade_date=date(2026, 4, 20),
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

    assert result.latest_trade_date == date(2026, 4, 20)
    mock_repository.save_last_success_trade_date.assert_called_once_with(
        "market_daily_sync",
        date(2026, 4, 20),
    )


def test_sync_rewinds_stale_checkpoint_to_db_latest_date(
    service: MarketDataSyncService,
    mock_gateway: MagicMock,
    mock_repository: MagicMock,
) -> None:
    """测试 checkpoint 超前于事实表时会回退到事实表最新日期。"""
    mock_repository.get_last_success_trade_date.return_value = date(2026, 4, 21)
    mock_repository.get_latest_trade_date_in_daily_bar.return_value = date(2026, 4, 16)
    mock_gateway.get_next_trade_date.return_value = date(2026, 4, 17)
    mock_gateway.get_latest_trade_date.return_value = date(2026, 4, 16)

    result = service.sync()

    assert result.latest_trade_date == date(2026, 4, 16)
    mock_gateway.get_next_trade_date.assert_called_once_with(date(2026, 4, 16))
    # 回退时会先校正 checkpoint，然后本轮因无新数据不再推进
    mock_repository.save_last_success_trade_date.assert_called_once_with(
        "market_daily_sync",
        date(2026, 4, 16),
    )
