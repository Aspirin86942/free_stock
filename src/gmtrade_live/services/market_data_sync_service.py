"""市场数据同步服务，负责三年全量回补与缺口补数。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from gmtrade_live.config import MarketAnalysisConfig
from gmtrade_live.gateways.gm_history_market_gateway import GMHistoryMarketGateway
from gmtrade_live.repositories.mysql_market_repository import MySQLMarketRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SyncResult:
    """同步结果。"""

    latest_trade_date: date
    inserted_rows: int
    updated_rows: int
    is_first_sync: bool


class MarketDataSyncService:
    """市场数据同步服务。"""

    def __init__(
        self,
        config: MarketAnalysisConfig,
        gateway: GMHistoryMarketGateway,
        repository: MySQLMarketRepository,
    ) -> None:
        self.config = config
        self.gateway = gateway
        self.repository = repository

    def sync(self) -> SyncResult:
        """执行同步：首次三年全量回补或增量补数。"""
        # 1. 获取最后成功同步的交易日
        last_success_date = self.repository.get_last_success_trade_date("market_daily_sync")

        # 2. 确定同步起止日期
        if last_success_date is None:
            # 首次同步：回补近 N 年
            start_date = self.gateway.get_trade_date_n_years_ago(self.config.history_years)
            is_first_sync = True
            logger.info(f"首次同步，回补近 {self.config.history_years} 年数据，起始日期: {start_date}")
        else:
            # 增量同步：从上次成功日期的下一个交易日开始
            start_date = self.gateway.get_next_trade_date(last_success_date)
            is_first_sync = False
            logger.info(f"增量同步，上次成功日期: {last_success_date}，起始日期: {start_date}")

        # 3. 获取最新已完成交易日
        end_date = self.gateway.get_latest_trade_date()
        logger.info(f"同步截止日期: {end_date}")

        # 4. 如果没有新数据，直接返回
        if start_date > end_date:
            logger.info("没有新数据需要同步")
            return SyncResult(
                latest_trade_date=last_success_date or end_date,
                inserted_rows=0,
                updated_rows=0,
                is_first_sync=is_first_sync,
            )

        # 5. 同步股票池（首次同步或定期更新）
        securities = self.gateway.get_security_master(self.config.universe)
        self.repository.upsert_security_master(securities)
        logger.info(f"股票池同步完成，共 {len(securities)} 只股票")

        # 6. 批量同步日线数据（按股票分批）
        symbols = [s.symbol for s in securities]
        batch_size = 50  # 每批 50 只股票
        total_inserted = 0
        total_updated = 0

        for i in range(0, len(symbols), batch_size):
            batch_symbols = symbols[i : i + batch_size]
            logger.info(
                f"同步批次 {i // batch_size + 1}/{(len(symbols) + batch_size - 1) // batch_size}，"
                f"股票数: {len(batch_symbols)}"
            )

            bars = self.gateway.fetch_daily_bars(batch_symbols, start_date, end_date)
            if bars:
                affected = self.repository.upsert_daily_bars(bars)
                total_inserted += affected
                logger.info(f"批次同步完成，影响行数: {affected}")

        # 7. 更新 checkpoint
        self.repository.save_last_success_trade_date("market_daily_sync", end_date)
        logger.info(f"同步完成，checkpoint 已更新至: {end_date}")

        return SyncResult(
            latest_trade_date=end_date,
            inserted_rows=total_inserted,
            updated_rows=total_updated,
            is_first_sync=is_first_sync,
        )
