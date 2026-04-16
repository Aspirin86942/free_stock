"""市场数据同步服务测试。"""

from datetime import date
from unittest.mock import MagicMock

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
    return MagicMock(spec=MySQLMarketRepository)


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
    mock_gateway.fetch_daily_bars.return_value = []
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
    mock_gateway.fetch_daily_bars.return_value = []
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
    """测试没有新数据时返回零。"""
    # 模拟已经是最新数据
    mock_repository.get_last_success_trade_date.return_value = date(2026, 4, 16)
    mock_gateway.get_next_trade_date.return_value = date(2026, 4, 17)
    mock_gateway.get_latest_trade_date.return_value = date(2026, 4, 16)

    result = service.sync()

    assert result.inserted_rows == 0
    assert result.latest_trade_date == date(2026, 4, 16)
    mock_gateway.get_security_master.assert_not_called()
    mock_repository.upsert_daily_bars.assert_not_called()


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
    mock_gateway.fetch_daily_bars.return_value = []
    mock_repository.upsert_daily_bars.return_value = 50

    result = service.sync()

    # 应该调用 2 次 fetch_daily_bars（100 只股票 / 50 = 2 批）
    assert mock_gateway.fetch_daily_bars.call_count == 2
