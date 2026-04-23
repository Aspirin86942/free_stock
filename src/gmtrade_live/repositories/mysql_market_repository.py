"""MySQL 市场数据仓储。"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

import pymysql
from pymysql.cursors import DictCursor

from gmtrade_live.config import MySQLConfig
from gmtrade_live.errors import ServiceError
from gmtrade_live.market_models import DailyBar, SecurityMaster

logger = logging.getLogger(__name__)


class RepositoryError(ServiceError):
    """仓储层错误。"""

    pass


class MySQLMarketRepository:
    """MySQL 市场数据仓储，负责 DDL、upsert、checkpoint 管理。"""

    def __init__(self, config: MySQLConfig) -> None:
        self.config = config
        self._connection: pymysql.Connection | None = None

    def connect(self) -> None:
        """建立数据库连接。"""
        try:
            self._connection = pymysql.connect(
                host=self.config.host,
                port=self.config.port,
                user=self.config.user,
                password=self.config.password,
                database=self.config.database,
                charset="utf8mb4",
                cursorclass=DictCursor,
            )
            logger.info(
                "MySQL 连接成功",
                extra={
                    "host": self.config.host,
                    "port": self.config.port,
                    "database": self.config.database,
                },
            )
        except pymysql.Error as exc:
            raise RepositoryError(
                code="repository.connection_failed",
                message=f"MySQL 连接失败: {exc}",
                retryable=True,
                context={"host": self.config.host, "database": self.config.database},
            ) from exc

    def close(self) -> None:
        """关闭数据库连接。"""
        if self._connection:
            self._connection.close()
            self._connection = None
            logger.info("MySQL 连接已关闭")

    def ensure_tables(self) -> None:
        """确保所有必需的表存在（DDL）。"""
        if not self._connection:
            raise RepositoryError(
                code="repository.not_connected",
                message="数据库未连接",
                retryable=False,
                context={},
            )

        ddl_statements = [
            # 股票池表
            """
            CREATE TABLE IF NOT EXISTS market_security_master (
                symbol VARCHAR(20) PRIMARY KEY,
                exchange VARCHAR(10) NOT NULL,
                name VARCHAR(100) NOT NULL,
                board VARCHAR(20) NOT NULL,
                listed_date DATE NOT NULL,
                INDEX idx_board (board),
                INDEX idx_listed_date (listed_date)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            # 日线数据表
            """
            CREATE TABLE IF NOT EXISTS market_daily_bar (
                symbol VARCHAR(20) NOT NULL,
                trade_date DATE NOT NULL,
                open DECIMAL(20, 4) NOT NULL,
                high DECIMAL(20, 4) NOT NULL,
                low DECIMAL(20, 4) NOT NULL,
                close DECIMAL(20, 4) NOT NULL,
                pre_close DECIMAL(20, 4) NOT NULL,
                volume BIGINT NOT NULL,
                amount DECIMAL(30, 2) NOT NULL,
                turnover_rate DECIMAL(10, 4),
                is_st BOOLEAN NOT NULL DEFAULT FALSE,
                suspended BOOLEAN NOT NULL DEFAULT FALSE,
                has_trade BOOLEAN NOT NULL DEFAULT TRUE,
                PRIMARY KEY (symbol, trade_date),
                INDEX idx_trade_date (trade_date),
                INDEX idx_symbol (symbol)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            # 同步检查点表
            """
            CREATE TABLE IF NOT EXISTS market_sync_checkpoint (
                job_name VARCHAR(100) PRIMARY KEY,
                last_success_trade_date DATE NOT NULL,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
        ]

        try:
            with self._connection.cursor() as cursor:
                for ddl in ddl_statements:
                    cursor.execute(ddl)
            self._connection.commit()
            logger.info("数据库表结构检查完成")
        except pymysql.Error as exc:
            raise RepositoryError(
                code="repository.ddl_failed",
                message=f"建表失败: {exc}",
                retryable=False,
                context={},
            ) from exc

    def upsert_security_master(self, securities: list[SecurityMaster]) -> int:
        """批量 upsert 股票池数据。"""
        if not self._connection:
            raise RepositoryError(
                code="repository.not_connected",
                message="数据库未连接",
                retryable=False,
                context={},
            )

        if not securities:
            return 0

        sql = """
            INSERT INTO market_security_master (symbol, exchange, name, board, listed_date)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                exchange = VALUES(exchange),
                name = VALUES(name),
                board = VALUES(board),
                listed_date = VALUES(listed_date)
        """

        try:
            with self._connection.cursor() as cursor:
                rows = [
                    (s.symbol, s.exchange, s.name, s.board, s.listed_date) for s in securities
                ]
                affected = cursor.executemany(sql, rows)
            self._connection.commit()
            logger.info(f"upsert 股票池数据完成，影响行数: {affected}")
            return affected
        except pymysql.Error as exc:
            self._connection.rollback()
            raise RepositoryError(
                code="repository.upsert_failed",
                message=f"upsert 股票池失败: {exc}",
                retryable=True,
                context={"count": len(securities)},
            ) from exc

    def upsert_daily_bars(self, bars: list[DailyBar]) -> int:
        """批量 upsert 日线数据。"""
        if not self._connection:
            raise RepositoryError(
                code="repository.not_connected",
                message="数据库未连接",
                retryable=False,
                context={},
            )

        if not bars:
            return 0

        sql = """
            INSERT INTO market_daily_bar (
                symbol, trade_date, open, high, low, close, pre_close,
                volume, amount, turnover_rate, is_st, suspended, has_trade
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                open = VALUES(open),
                high = VALUES(high),
                low = VALUES(low),
                close = VALUES(close),
                pre_close = VALUES(pre_close),
                volume = VALUES(volume),
                amount = VALUES(amount),
                turnover_rate = VALUES(turnover_rate),
                is_st = VALUES(is_st),
                suspended = VALUES(suspended),
                has_trade = VALUES(has_trade)
        """

        try:
            with self._connection.cursor() as cursor:
                rows = [
                    (
                        b.symbol,
                        b.trade_date,
                        b.open,
                        b.high,
                        b.low,
                        b.close,
                        b.pre_close,
                        b.volume,
                        b.amount,
                        b.turnover_rate,
                        b.is_st,
                        b.suspended,
                        b.has_trade,
                    )
                    for b in bars
                ]
                affected = cursor.executemany(sql, rows)
            self._connection.commit()
            logger.info(f"upsert 日线数据完成，影响行数: {affected}")
            return affected
        except pymysql.Error as exc:
            self._connection.rollback()
            raise RepositoryError(
                code="repository.upsert_failed",
                message=f"upsert 日线数据失败: {exc}",
                retryable=True,
                context={"count": len(bars)},
            ) from exc

    def get_last_success_trade_date(self, job_name: str) -> date | None:
        """获取指定任务的最后成功同步日期。"""
        if not self._connection:
            raise RepositoryError(
                code="repository.not_connected",
                message="数据库未连接",
                retryable=False,
                context={},
            )

        sql = "SELECT last_success_trade_date FROM market_sync_checkpoint WHERE job_name = %s"

        try:
            with self._connection.cursor() as cursor:
                cursor.execute(sql, (job_name,))
                row = cursor.fetchone()
                if row:
                    return row["last_success_trade_date"]
                return None
        except pymysql.Error as exc:
            raise RepositoryError(
                code="repository.query_failed",
                message=f"查询 checkpoint 失败: {exc}",
                retryable=True,
                context={"job_name": job_name},
            ) from exc

    def save_last_success_trade_date(self, job_name: str, trade_date: date) -> None:
        """保存指定任务的最后成功同步日期。"""
        if not self._connection:
            raise RepositoryError(
                code="repository.not_connected",
                message="数据库未连接",
                retryable=False,
                context={},
            )

        sql = """
            INSERT INTO market_sync_checkpoint (job_name, last_success_trade_date)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE
                last_success_trade_date = VALUES(last_success_trade_date)
        """

        try:
            with self._connection.cursor() as cursor:
                cursor.execute(sql, (job_name, trade_date))
            self._connection.commit()
            logger.info(f"checkpoint 已更新: {job_name} -> {trade_date}")
        except pymysql.Error as exc:
            self._connection.rollback()
            raise RepositoryError(
                code="repository.checkpoint_failed",
                message=f"保存 checkpoint 失败: {exc}",
                retryable=True,
                context={"job_name": job_name, "trade_date": str(trade_date)},
            ) from exc

    def get_daily_bars(
        self, symbols: list[str], start_date: date, end_date: date
    ) -> list[DailyBar]:
        """查询指定股票和日期范围的日线数据。"""
        if not self._connection:
            raise RepositoryError(
                code="repository.not_connected",
                message="数据库未连接",
                retryable=False,
                context={},
            )

        if not symbols:
            return []

        placeholders = ",".join(["%s"] * len(symbols))
        sql = f"""
            SELECT symbol, trade_date, open, high, low, close, pre_close,
                   volume, amount, turnover_rate, is_st, suspended, has_trade
            FROM market_daily_bar
            WHERE symbol IN ({placeholders})
              AND trade_date BETWEEN %s AND %s
            ORDER BY trade_date, symbol
        """

        try:
            with self._connection.cursor() as cursor:
                cursor.execute(sql, (*symbols, start_date, end_date))
                rows = cursor.fetchall()

            return [
                DailyBar(
                    symbol=row["symbol"],
                    trade_date=row["trade_date"],
                    open=Decimal(str(row["open"])),
                    high=Decimal(str(row["high"])),
                    low=Decimal(str(row["low"])),
                    close=Decimal(str(row["close"])),
                    pre_close=Decimal(str(row["pre_close"])),
                    volume=int(row["volume"]),
                    amount=Decimal(str(row["amount"])),
                    turnover_rate=Decimal(str(row["turnover_rate"]))
                    if row["turnover_rate"]
                    else None,
                    is_st=bool(row["is_st"]),
                    suspended=bool(row["suspended"]),
                    has_trade=bool(row["has_trade"]),
                )
                for row in rows
            ]
        except pymysql.Error as exc:
            raise RepositoryError(
                code="repository.query_failed",
                message=f"查询日线数据失败: {exc}",
                retryable=True,
                context={
                    "symbol_count": len(symbols),
                    "start_date": str(start_date),
                    "end_date": str(end_date),
                },
            ) from exc

    def get_daily_bars_by_date(self, trade_date: date) -> list[DailyBar]:
        """查询指定交易日所有股票的日线数据。"""
        if not self._connection:
            raise RepositoryError(
                code="repository.not_connected",
                message="数据库未连接",
                retryable=False,
                context={},
            )

        sql = """
            SELECT symbol, trade_date, open, high, low, close, pre_close,
                   volume, amount, turnover_rate, is_st, suspended, has_trade
            FROM market_daily_bar
            WHERE trade_date = %s
            ORDER BY symbol
        """

        try:
            with self._connection.cursor() as cursor:
                cursor.execute(sql, (trade_date,))
                rows = cursor.fetchall()

            return [
                DailyBar(
                    symbol=row["symbol"],
                    trade_date=row["trade_date"],
                    open=Decimal(str(row["open"])),
                    high=Decimal(str(row["high"])),
                    low=Decimal(str(row["low"])),
                    close=Decimal(str(row["close"])),
                    pre_close=Decimal(str(row["pre_close"])),
                    volume=int(row["volume"]),
                    amount=Decimal(str(row["amount"])),
                    turnover_rate=Decimal(str(row["turnover_rate"]))
                    if row["turnover_rate"]
                    else None,
                    is_st=bool(row["is_st"]),
                    suspended=bool(row["suspended"]),
                    has_trade=bool(row["has_trade"]),
                )
                for row in rows
            ]
        except pymysql.Error as exc:
            raise RepositoryError(
                code="repository.query_failed",
                message=f"查询单日日线数据失败: {exc}",
                retryable=True,
                context={"trade_date": str(trade_date)},
            ) from exc

    def get_all_symbols(self) -> list[str]:
        """获取所有股票代码。"""
        if not self._connection:
            raise RepositoryError(
                code="repository.not_connected",
                message="数据库未连接",
                retryable=False,
                context={},
            )

        sql = "SELECT symbol FROM market_security_master ORDER BY symbol"

        try:
            with self._connection.cursor() as cursor:
                cursor.execute(sql)
                rows = cursor.fetchall()
            return [row["symbol"] for row in rows]
        except pymysql.Error as exc:
            raise RepositoryError(
                code="repository.query_failed",
                message=f"查询股票列表失败: {exc}",
                retryable=True,
                context={},
            ) from exc

    def get_security_name_map(self, symbols: list[str]) -> dict[str, str]:
        """按 symbol 批量查询证券名称映射。"""
        if not self._connection:
            raise RepositoryError(
                code="repository.not_connected",
                message="数据库未连接",
                retryable=False,
                context={},
            )

        if not symbols:
            return {}

        placeholders = ",".join(["%s"] * len(symbols))
        sql = f"""
            SELECT symbol, name
            FROM market_security_master
            WHERE symbol IN ({placeholders})
        """
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(sql, tuple(symbols))
                rows = cursor.fetchall()
            return {
                str(row["symbol"]): str(row["name"])
                for row in rows
                if row.get("symbol") is not None and row.get("name") is not None
            }
        except pymysql.Error as exc:
            raise RepositoryError(
                code="repository.query_failed",
                message=f"查询证券名称映射失败: {exc}",
                retryable=True,
                context={"symbol_count": len(symbols)},
            ) from exc

    def get_security_listed_date_map(self, symbols: list[str]) -> dict[str, date]:
        """按 symbol 批量查询证券上市日期映射。"""
        if not self._connection:
            raise RepositoryError(
                code="repository.not_connected",
                message="数据库未连接",
                retryable=False,
                context={},
            )

        if not symbols:
            return {}

        placeholders = ",".join(["%s"] * len(symbols))
        sql = f"""
            SELECT symbol, listed_date
            FROM market_security_master
            WHERE symbol IN ({placeholders})
        """

        try:
            with self._connection.cursor() as cursor:
                cursor.execute(sql, tuple(symbols))
                rows = cursor.fetchall()
            # 上层通常按 symbol 直接索引日期，这里保持一行一值的映射结构，避免额外转换成本。
            return {
                str(row["symbol"]): row["listed_date"]
                for row in rows
                if row.get("symbol") is not None and row.get("listed_date") is not None
            }
        except pymysql.Error as exc:
            raise RepositoryError(
                code="repository.query_failed",
                message=f"查询证券上市日期映射失败: {exc}",
                retryable=True,
                context={"symbol_count": len(symbols)},
            ) from exc

    def get_recent_trade_dates(self, end_date: date, limit: int) -> list[date]:
        """获取最近 N 个交易日（从 end_date 往前推）。"""
        if not self._connection:
            raise RepositoryError(
                code="repository.not_connected",
                message="数据库未连接",
                retryable=False,
                context={},
            )

        sql = """
            SELECT DISTINCT trade_date
            FROM market_daily_bar
            WHERE trade_date <= %s
            ORDER BY trade_date DESC
            LIMIT %s
        """

        try:
            with self._connection.cursor() as cursor:
                cursor.execute(sql, (end_date, limit))
                rows = cursor.fetchall()
            # 返回时按升序排列
            return sorted([row["trade_date"] for row in rows])
        except pymysql.Error as exc:
            raise RepositoryError(
                code="repository.query_failed",
                message=f"查询最近交易日失败: {exc}",
                retryable=True,
                context={"end_date": str(end_date), "limit": limit},
            ) from exc

    def get_trade_dates_between(self, start_date: date, end_date: date) -> list[date]:
        """获取指定日期区间内的交易日列表，按时间顺序返回。"""
        if not self._connection:
            raise RepositoryError(
                code="repository.not_connected",
                message="数据库未连接",
                retryable=False,
                context={},
            )

        sql = """
            SELECT DISTINCT trade_date
            FROM market_daily_bar
            WHERE trade_date BETWEEN %s AND %s
            ORDER BY trade_date ASC
        """

        try:
            with self._connection.cursor() as cursor:
                cursor.execute(sql, (start_date, end_date))
                rows = cursor.fetchall()
            # 再做一次显式排序，避免上游或数据库层出现顺序波动时影响调用方。
            return sorted(row["trade_date"] for row in rows)
        except pymysql.Error as exc:
            raise RepositoryError(
                code="repository.query_failed",
                message=f"查询区间交易日失败: {exc}",
                retryable=True,
                context={"start_date": str(start_date), "end_date": str(end_date)},
            ) from exc

    def get_latest_trade_date_in_daily_bar(self) -> date | None:
        """获取事实表 market_daily_bar 中已落库的最新交易日。"""
        if not self._connection:
            raise RepositoryError(
                code="repository.not_connected",
                message="数据库未连接",
                retryable=False,
                context={},
            )

        sql = "SELECT MAX(trade_date) AS latest_trade_date FROM market_daily_bar"
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(sql)
                row = cursor.fetchone()
            if not row:
                return None
            return row["latest_trade_date"]
        except pymysql.Error as exc:
            raise RepositoryError(
                code="repository.query_failed",
                message=f"查询最新交易日失败: {exc}",
                retryable=True,
                context={},
            ) from exc
