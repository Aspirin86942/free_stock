"""MySQL 市场数据仓储测试。"""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from gmtrade_live.config import MySQLConfig
from gmtrade_live.repositories import MySQLMarketRepository
from gmtrade_live.repositories.mysql_market_repository import RepositoryError


@pytest.fixture
def mysql_config() -> MySQLConfig:
    return MySQLConfig(
        host="127.0.0.1",
        port=3306,
        database="test_market_data",
        user="test_user",
        password="test_password",
    )


@pytest.fixture
def repository(mysql_config: MySQLConfig) -> MySQLMarketRepository:
    return MySQLMarketRepository(mysql_config)


def test_repository_raises_error_when_not_connected(repository: MySQLMarketRepository) -> None:
    """测试未连接时抛出错误。"""
    with pytest.raises(RepositoryError) as exc_info:
        repository.ensure_tables()

    assert exc_info.value.code == "repository.not_connected"


def test_upsert_security_master_returns_zero_for_empty_list(
    repository: MySQLMarketRepository,
) -> None:
    """测试空列表返回 0。"""
    with patch.object(repository, "_connection", MagicMock()):
        result = repository.upsert_security_master([])
        assert result == 0


def test_upsert_daily_bars_returns_zero_for_empty_list(
    repository: MySQLMarketRepository,
) -> None:
    """测试空列表返回 0。"""
    with patch.object(repository, "_connection", MagicMock()):
        result = repository.upsert_daily_bars([])
        assert result == 0


def test_get_last_success_trade_date_returns_none_when_not_found(
    repository: MySQLMarketRepository,
) -> None:
    """测试 checkpoint 不存在时返回 None。"""
    mock_connection = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None
    mock_connection.cursor.return_value.__enter__.return_value = mock_cursor

    with patch.object(repository, "_connection", mock_connection):
        result = repository.get_last_success_trade_date("test_job")
        assert result is None


def test_get_last_success_trade_date_returns_date_when_found(
    repository: MySQLMarketRepository,
) -> None:
    """测试 checkpoint 存在时返回日期。"""
    mock_connection = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {"last_success_trade_date": date(2026, 4, 15)}
    mock_connection.cursor.return_value.__enter__.return_value = mock_cursor

    with patch.object(repository, "_connection", mock_connection):
        result = repository.get_last_success_trade_date("test_job")
        assert result == date(2026, 4, 15)


def test_get_all_symbols_returns_empty_list_when_no_data(
    repository: MySQLMarketRepository,
) -> None:
    """测试无数据时返回空列表。"""
    mock_connection = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []
    mock_connection.cursor.return_value.__enter__.return_value = mock_cursor

    with patch.object(repository, "_connection", mock_connection):
        result = repository.get_all_symbols()
        assert result == []


def test_get_daily_bars_returns_empty_list_for_empty_symbols(
    repository: MySQLMarketRepository,
) -> None:
    """测试空股票列表返回空列表。"""
    with patch.object(repository, "_connection", MagicMock()):
        result = repository.get_daily_bars([], date(2026, 4, 1), date(2026, 4, 15))
        assert result == []


def test_get_recent_trade_dates_returns_sorted_dates(
    repository: MySQLMarketRepository,
) -> None:
    """测试返回排序后的交易日列表。"""
    mock_connection = MagicMock()
    mock_cursor = MagicMock()
    # 模拟数据库返回降序
    mock_cursor.fetchall.return_value = [
        {"trade_date": date(2026, 4, 15)},
        {"trade_date": date(2026, 4, 14)},
        {"trade_date": date(2026, 4, 11)},
    ]
    mock_connection.cursor.return_value.__enter__.return_value = mock_cursor

    with patch.object(repository, "_connection", mock_connection):
        result = repository.get_recent_trade_dates(date(2026, 4, 15), 3)
        # 应该返回升序
        assert result == [date(2026, 4, 11), date(2026, 4, 14), date(2026, 4, 15)]


def test_get_security_name_map_returns_empty_for_empty_symbols(
    repository: MySQLMarketRepository,
) -> None:
    """测试空 symbol 列表返回空映射。"""
    with patch.object(repository, "_connection", MagicMock()):
        assert repository.get_security_name_map([]) == {}


def test_get_security_name_map_returns_symbol_name_dict(
    repository: MySQLMarketRepository,
) -> None:
    """测试返回 symbol -> name 映射。"""
    mock_connection = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        {"symbol": "SHSE.600000", "name": "*ST示例"},
        {"symbol": "SZSE.000001", "name": "平安银行"},
    ]
    mock_connection.cursor.return_value.__enter__.return_value = mock_cursor

    with patch.object(repository, "_connection", mock_connection):
        result = repository.get_security_name_map(["SHSE.600000", "SZSE.000001"])
        assert result == {
            "SHSE.600000": "*ST示例",
            "SZSE.000001": "平安银行",
        }


def test_get_security_listed_date_map_returns_symbol_listed_date_dict(
    repository: MySQLMarketRepository,
) -> None:
    """测试返回 symbol -> listed_date 映射。"""
    mock_connection = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        {"symbol": "SHSE.600000", "listed_date": date(2007, 4, 27)},
        {"symbol": "SZSE.000001", "listed_date": date(1991, 4, 3)},
    ]
    mock_connection.cursor.return_value.__enter__.return_value = mock_cursor

    with patch.object(repository, "_connection", mock_connection):
        result = repository.get_security_listed_date_map(
            ["SHSE.600000", "SZSE.000001"]
        )
        assert result == {
            "SHSE.600000": date(2007, 4, 27),
            "SZSE.000001": date(1991, 4, 3),
        }


def test_get_trade_dates_between_returns_sorted_dates(
    repository: MySQLMarketRepository,
) -> None:
    """测试返回升序交易日列表。"""
    mock_connection = MagicMock()
    mock_cursor = MagicMock()
    # 模拟数据库返回顺序不稳定，仓储层需要统一输出升序结果
    mock_cursor.fetchall.return_value = [
        {"trade_date": date(2026, 4, 15)},
        {"trade_date": date(2026, 4, 11)},
        {"trade_date": date(2026, 4, 14)},
    ]
    mock_connection.cursor.return_value.__enter__.return_value = mock_cursor

    with patch.object(repository, "_connection", mock_connection):
        result = repository.get_trade_dates_between(date(2026, 4, 10), date(2026, 4, 15))
        assert result == [date(2026, 4, 11), date(2026, 4, 14), date(2026, 4, 15)]
