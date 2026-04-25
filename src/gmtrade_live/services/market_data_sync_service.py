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

    _TURNOVER_REPAIR_TRADE_DAYS = 2
    _SYNC_BATCH_SIZE = 50

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
        latest_trade_date_in_db = self.repository.get_latest_trade_date_in_daily_bar()

        effective_last_success_date = last_success_date
        if (
            last_success_date is not None
            and latest_trade_date_in_db is not None
            and last_success_date > latest_trade_date_in_db
        ):
            logger.warning(
                "检测到 checkpoint 超前于事实表，自动回退到事实表最新交易日",
                extra={
                    "checkpoint_trade_date": str(last_success_date),
                    "latest_trade_date_in_db": str(latest_trade_date_in_db),
                },
            )
            effective_last_success_date = latest_trade_date_in_db
            self.repository.save_last_success_trade_date(
                "market_daily_sync",
                latest_trade_date_in_db,
            )
        elif last_success_date is not None and latest_trade_date_in_db is None:
            logger.warning(
                "checkpoint 存在但事实表为空，本轮按首次同步执行",
                extra={"checkpoint_trade_date": str(last_success_date)},
            )
            effective_last_success_date = None

        # 2. 确定同步起止日期
        if effective_last_success_date is None:
            # 首次同步：回补近 N 年
            start_date = self.gateway.get_trade_date_n_years_ago(self.config.history_years)
            is_first_sync = True
            logger.info(f"首次同步，回补近 {self.config.history_years} 年数据，起始日期: {start_date}")
        else:
            # 增量同步：从上次成功日期的下一个交易日开始
            start_date = self.gateway.get_next_trade_date(effective_last_success_date)
            is_first_sync = False
            logger.info(
                f"增量同步，上次成功日期: {effective_last_success_date}，起始日期: {start_date}"
            )

        # 3. 获取最新已完成交易日
        end_date = self.gateway.get_latest_trade_date()
        logger.info(f"同步截止日期: {end_date}")

        # 4. 同步股票池并识别新纳入 symbol
        securities = self.gateway.get_security_master(self.config.universe)
        current_symbols = [security.symbol for security in securities]
        self.repository.upsert_security_master(securities)
        logger.info(f"股票池同步完成，共 {len(securities)} 只股票")

        backfill_inserted_rows = 0

        # 5. 如果没有普通增量窗口，优先回补新 symbol 历史
        if start_date > end_date:
            logger.info("没有新数据需要同步")
            symbols_needing_history_backfill = self._get_symbols_needing_history_backfill(
                current_symbols,
                end_date,
            )
            if symbols_needing_history_backfill:
                backfill_inserted_rows, _ = self._backfill_new_symbols(
                    symbols_needing_history_backfill,
                    end_date,
                )

            repaired_rows = self._repair_recent_turnover_rates(
                latest_trade_date=latest_trade_date_in_db or effective_last_success_date or end_date
            )
            return SyncResult(
                latest_trade_date=effective_last_success_date or latest_trade_date_in_db or end_date,
                inserted_rows=backfill_inserted_rows + repaired_rows,
                updated_rows=0,
                is_first_sync=is_first_sync,
            )

        # 6. 有普通增量窗口时，新纳入 symbol 先回补历史，再执行全量增量同步
        if not is_first_sync:
            coexist_backfill_end_date = effective_last_success_date or end_date
            symbols_needing_history_backfill = self._get_symbols_needing_history_backfill(
                current_symbols,
                coexist_backfill_end_date,
            )
            if symbols_needing_history_backfill:
                backfill_inserted_rows, _ = self._backfill_new_symbols(
                    symbols_needing_history_backfill,
                    coexist_backfill_end_date,
                )

        # 7. 批量同步日线数据（按股票分批）
        total_inserted, latest_batch_trade_date = self._sync_symbol_batches(
            symbols=current_symbols,
            start_date=start_date,
            end_date=end_date,
        )
        total_inserted += backfill_inserted_rows
        total_updated = 0
        latest_synced_trade_date = latest_batch_trade_date or effective_last_success_date

        # 8. 更新 checkpoint（仅由普通增量窗口驱动，不受新 symbol 历史回补影响）
        if (
            latest_synced_trade_date is not None
            and (
                effective_last_success_date is None
                or latest_synced_trade_date > effective_last_success_date
            )
        ):
            self.repository.save_last_success_trade_date("market_daily_sync", latest_synced_trade_date)
            logger.info(f"同步完成，checkpoint 已更新至: {latest_synced_trade_date}")
        else:
            logger.info("本轮无新增落库交易日，checkpoint 不推进")

        return SyncResult(
            latest_trade_date=latest_synced_trade_date or latest_trade_date_in_db or end_date,
            inserted_rows=total_inserted,
            updated_rows=total_updated,
            is_first_sync=is_first_sync,
        )

    def _get_symbols_needing_history_backfill(
        self,
        symbols: list[str],
        backfill_end_date: date,
    ) -> list[str]:
        """返回在历史回补窗口内仍无日线数据的 symbol 列表。"""
        if not symbols:
            return []

        history_start_date = self.gateway.get_trade_date_n_years_ago(self.config.history_years)
        if history_start_date > backfill_end_date:
            return []

        # 这里按“窗口内是否已有任何 bars”判断，确保仅写入 security_master 后失败的重试场景仍能补历史。
        existing_bars = self.repository.get_daily_bars(
            symbols,
            history_start_date,
            backfill_end_date,
        )
        symbols_with_history = {bar.symbol for bar in existing_bars}
        return [symbol for symbol in symbols if symbol not in symbols_with_history]

    def _backfill_new_symbols(
        self,
        symbols: list[str],
        end_date: date,
    ) -> tuple[int, date | None]:
        """回补新纳入股票在历史窗口内的日线数据。"""
        if not symbols:
            return 0, None
        history_start_date = self.gateway.get_trade_date_n_years_ago(self.config.history_years)
        logger.info(
            "开始回补新纳入 symbol 历史数据",
            extra={
                "new_symbol_count": len(symbols),
                "history_start_date": str(history_start_date),
                "history_end_date": str(end_date),
            },
        )
        return self._sync_symbol_batches(
            symbols=symbols,
            start_date=history_start_date,
            end_date=end_date,
        )

    def _sync_symbol_batches(
        self,
        symbols: list[str],
        start_date: date,
        end_date: date,
    ) -> tuple[int, date | None]:
        """按批次同步指定 symbol 列表的日线数据。"""
        total_inserted = 0
        latest_synced_trade_date: date | None = None
        if not symbols:
            return total_inserted, latest_synced_trade_date

        for i in range(0, len(symbols), self._SYNC_BATCH_SIZE):
            batch_symbols = symbols[i : i + self._SYNC_BATCH_SIZE]
            logger.info(
                f"同步批次 {i // self._SYNC_BATCH_SIZE + 1}/"
                f"{(len(symbols) + self._SYNC_BATCH_SIZE - 1) // self._SYNC_BATCH_SIZE}，"
                f"股票数: {len(batch_symbols)}"
            )
            bars = self.gateway.fetch_daily_bars(batch_symbols, start_date, end_date)
            if not bars:
                continue
            affected = self.repository.upsert_daily_bars(bars)
            total_inserted += affected
            logger.info(f"批次同步完成，影响行数: {affected}")
            batch_latest_trade_date = max(bar.trade_date for bar in bars)
            if (
                latest_synced_trade_date is None
                or batch_latest_trade_date > latest_synced_trade_date
            ):
                latest_synced_trade_date = batch_latest_trade_date
        return total_inserted, latest_synced_trade_date

    def _repair_recent_turnover_rates(self, latest_trade_date: date | None) -> int:
        """在无新增交易日时，回补最近窗口的换手率数据。"""
        if latest_trade_date is None:
            return 0

        trade_dates_needing_repair = self.repository.get_trade_dates_with_missing_turnover(
            end_date=latest_trade_date,
            limit=self._TURNOVER_REPAIR_TRADE_DAYS,
        )
        if not trade_dates_needing_repair:
            logger.info(
                "近期换手率已完整，无需修复",
                extra={
                    "latest_trade_date": str(latest_trade_date),
                    "repair_trade_day_window": self._TURNOVER_REPAIR_TRADE_DAYS,
                },
            )
            return 0

        symbols = self.repository.get_all_symbols()
        if not symbols:
            return 0

        repair_start_date = trade_dates_needing_repair[0]
        repair_end_date = trade_dates_needing_repair[-1]
        total_affected = 0

        logger.info(
            "开始执行近期换手率修复",
            extra={
                "repair_start_date": str(repair_start_date),
                "repair_end_date": str(repair_end_date),
                "repair_trade_date_count": len(trade_dates_needing_repair),
                "symbol_count": len(symbols),
            },
        )

        for i in range(0, len(symbols), self._SYNC_BATCH_SIZE):
            batch_symbols = symbols[i : i + self._SYNC_BATCH_SIZE]
            bars = self.gateway.fetch_daily_bars(
                batch_symbols,
                repair_start_date,
                repair_end_date,
            )
            if not bars:
                continue
            affected = self.repository.upsert_daily_bars(bars)
            total_affected += affected

        logger.info(
            "近期换手率修复完成",
            extra={
                "repair_start_date": str(repair_start_date),
                "repair_end_date": str(repair_end_date),
                "affected_rows": total_affected,
            },
        )
        return total_affected
