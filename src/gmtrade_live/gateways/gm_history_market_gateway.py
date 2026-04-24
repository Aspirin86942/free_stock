"""掘金历史行情网关，封装交易日历与历史日线数据读取。"""

from __future__ import annotations

import importlib
import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from gmtrade_live.errors import ServiceError
from gmtrade_live.market_models import DailyBar, SecurityMaster
from gmtrade_live.precision import normalize_price

logger = logging.getLogger(__name__)


class GMHistoryMarketGateway:
    """掘金历史市场数据网关。"""

    def __init__(self, api_module: Any | None = None) -> None:
        self._api = api_module or importlib.import_module("gm.api")

    def connect(self, token: str, endpoint: str) -> None:
        """连接掘金 API。"""
        self._api.set_token(token)
        # 注意：掘金 API 不需要 set_endpoint，endpoint 由掘金终端自动处理
        logger.info(f"掘金历史行情网关已连接，token 已设置")

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
        # 沪深主板: SHSE + SZSE，创业板: SZSE.300xxx，科创板: SHSE.688xxx
        try:
            instruments = self._api.get_instruments(
                exchanges="SHSE,SZSE",
                sec_types=[1],  # 1 = 股票
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

            # 判断板块
            if symbol.startswith("SHSE.688"):
                board = "star"
            elif symbol.startswith("SZSE.300"):
                board = "gem"
            elif symbol.startswith("SHSE.6") or symbol.startswith("SZSE.0"):
                board = "main"
            else:
                # 跳过其他（如北交所、指数等）
                continue

            # 解析上市日期（格式：YYYY-MM-DD）
            try:
                listed_date = date.fromisoformat(listed_date_str.split()[0])
            except (ValueError, IndexError):
                logger.warning(f"跳过无效上市日期的股票: {symbol}, listed_date={listed_date_str}")
                continue

            results.append(
                SecurityMaster(
                    symbol=symbol,
                    exchange=exchange,
                    name=name,
                    board=board,
                    listed_date=listed_date,
                )
            )

        logger.info(f"获取股票池完成，共 {len(results)} 只股票")
        return results

    def fetch_daily_bars(
        self, symbols: list[str], start_date: date, end_date: date
    ) -> list[DailyBar]:
        """批量拉取历史日线数据。"""
        if not symbols:
            return []

        # 掘金 API: history(symbol, frequency, start_time, end_time, fields, adjust)
        # frequency='1d' 表示日线
        try:
            bars = self._api.history(
                symbol=",".join(symbols),
                frequency="1d",
                start_time=start_date.isoformat(),
                end_time=end_date.isoformat(),
                fields="symbol,eob,open,high,low,close,pre_close,volume,amount,bob",
                adjust=1,  # 前复权
                df=False,  # 返回字典列表
            )
        except Exception as exc:
            raise ServiceError(
                code="gm.fetch_history_failed",
                message=f"拉取历史日线失败: {exc}",
                retryable=True,
                context={
                    "symbol_count": len(symbols),
                    "start_date": str(start_date),
                    "end_date": str(end_date),
                },
            ) from exc

        turnover_rate_map = self._fetch_turnover_rate_map(
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
        )

        results: list[DailyBar] = []
        for bar in bars:
            symbol = str(bar["symbol"])
            trade_date_str = str(bar["eob"]).split()[0]  # eob: end of bar
            trade_date = date.fromisoformat(trade_date_str)

            # 判断是否有成交
            volume = int(bar.get("volume", 0))
            amount = Decimal(str(bar.get("amount", 0)))
            has_trade = volume > 0 and amount > 0

            # 判断是否停牌（简化：如果 open/high/low/close 都为 0，视为停牌）
            open_price = normalize_price(bar.get("open", 0))
            high_price = normalize_price(bar.get("high", 0))
            low_price = normalize_price(bar.get("low", 0))
            close_price = normalize_price(bar.get("close", 0))
            suspended = (
                open_price == Decimal("0")
                and high_price == Decimal("0")
                and low_price == Decimal("0")
                and close_price == Decimal("0")
            )

            # history 接口通常不返回换手率，优先使用 daily_basic 补齐的数据。
            turnover_rate = turnover_rate_map.get((symbol, trade_date))
            if turnover_rate is None:
                turnover_rate = self._parse_turnover_rate_from_history_bar(bar)

            # ST 状态（掘金可能不提供，暂时设为 False）
            # TODO: 需要从其他数据源获取 ST 状态
            is_st = False

            results.append(
                DailyBar(
                    symbol=symbol,
                    trade_date=trade_date,
                    open=open_price,
                    high=high_price,
                    low=low_price,
                    close=close_price,
                    pre_close=normalize_price(bar.get("pre_close", 0)),
                    volume=volume,
                    amount=amount,
                    turnover_rate=turnover_rate,
                    is_st=is_st,
                    suspended=suspended,
                    has_trade=has_trade,
                )
            )

        logger.info(
            f"拉取历史日线完成，共 {len(results)} 条记录",
            extra={
                "symbol_count": len(symbols),
                "start_date": str(start_date),
                "end_date": str(end_date),
            },
        )
        return results

    def _fetch_turnover_rate_map(
        self,
        symbols: list[str],
        start_date: date,
        end_date: date,
    ) -> dict[tuple[str, date], Decimal]:
        """获取换手率映射，key=(symbol, trade_date)。"""
        trade_dates = self.get_trade_dates(start_date, end_date)
        if not trade_dates:
            return {}

        # 对于日常增量（通常只有 1 个交易日），按交易日批量拉取能显著减少请求次数；
        # 对于首次多日回补，按股票拉取能避免按交易日调用过多接口。
        if len(trade_dates) <= len(symbols):
            turnover_rate_map = self._fetch_turnover_rate_map_by_trade_date(
                symbols=symbols,
                trade_dates=trade_dates,
            )
            fetch_mode = "by_trade_date"
        else:
            turnover_rate_map = self._fetch_turnover_rate_map_by_symbol(
                symbols=symbols,
                start_date=start_date,
                end_date=end_date,
            )
            fetch_mode = "by_symbol"

        logger.info(
            "换手率补齐完成",
            extra={
                "fetch_mode": fetch_mode,
                "symbol_count": len(symbols),
                "trade_date_count": len(trade_dates),
                "turnover_points": len(turnover_rate_map),
            },
        )
        return turnover_rate_map

    def _fetch_turnover_rate_map_by_trade_date(
        self,
        symbols: list[str],
        trade_dates: list[date],
    ) -> dict[tuple[str, date], Decimal]:
        """按交易日批量拉取换手率（stk_get_daily_basic_pt）。"""
        turnover_rate_map: dict[tuple[str, date], Decimal] = {}
        symbols_text = ",".join(symbols)

        for trade_date in trade_dates:
            try:
                rows = self._api.stk_get_daily_basic_pt(
                    symbols=symbols_text,
                    fields="turnrate",
                    trade_date=trade_date.isoformat(),
                    df=False,
                )
            except Exception:
                logger.exception(
                    "按交易日拉取换手率失败",
                    extra={
                        "trade_date": str(trade_date),
                        "symbol_count": len(symbols),
                    },
                )
                continue
            self._merge_turnover_rate_rows(turnover_rate_map, rows)
        return turnover_rate_map

    def _fetch_turnover_rate_map_by_symbol(
        self,
        symbols: list[str],
        start_date: date,
        end_date: date,
    ) -> dict[tuple[str, date], Decimal]:
        """按股票拉取换手率（stk_get_daily_basic）。"""
        turnover_rate_map: dict[tuple[str, date], Decimal] = {}
        for symbol in symbols:
            try:
                rows = self._api.stk_get_daily_basic(
                    symbol=symbol,
                    fields="turnrate",
                    start_date=start_date.isoformat(),
                    end_date=end_date.isoformat(),
                    df=False,
                )
            except Exception:
                logger.exception(
                    "按股票拉取换手率失败",
                    extra={
                        "symbol": symbol,
                        "start_date": str(start_date),
                        "end_date": str(end_date),
                    },
                )
                continue
            self._merge_turnover_rate_rows(turnover_rate_map, rows)
        return turnover_rate_map

    def _merge_turnover_rate_rows(
        self,
        turnover_rate_map: dict[tuple[str, date], Decimal],
        rows: Any,
    ) -> None:
        """将 daily_basic 返回行写入换手率映射。"""
        if not isinstance(rows, list):
            return

        for row in rows:
            if not isinstance(row, dict):
                continue

            symbol = str(row.get("symbol", "")).strip()
            trade_date_raw = row.get("trade_date")
            turnover_rate_raw = row.get("turnrate")
            if not symbol or trade_date_raw in (None, "") or turnover_rate_raw in (None, ""):
                continue

            try:
                trade_date = date.fromisoformat(str(trade_date_raw).split()[0])
                turnover_rate = Decimal(str(turnover_rate_raw))
            except (ValueError, ArithmeticError):
                continue

            turnover_rate_map[(symbol, trade_date)] = turnover_rate

    def _parse_turnover_rate_from_history_bar(self, bar: dict[str, Any]) -> Decimal | None:
        """兼容 history 可能返回的换手率字段。"""
        for key in ("turnover_rate", "turnrate", "turn_rate"):
            value = bar.get(key)
            if value in (None, ""):
                continue
            try:
                return Decimal(str(value))
            except (ValueError, ArithmeticError):
                continue
        return None

    def get_trade_dates(self, start_date: date, end_date: date) -> list[date]:
        """获取指定日期范围内的交易日列表。"""
        try:
            # 掘金 API: get_trading_dates(exchange, start_date, end_date)
            trade_dates_str = self._api.get_trading_dates(
                exchange="SHSE", start_date=start_date.isoformat(), end_date=end_date.isoformat()
            )
            return [date.fromisoformat(d.split()[0]) for d in trade_dates_str]
        except Exception as exc:
            raise ServiceError(
                code="gm.fetch_trade_dates_failed",
                message=f"获取交易日列表失败: {exc}",
                retryable=True,
                context={"start_date": str(start_date), "end_date": str(end_date)},
            ) from exc

    def get_latest_trade_date(self, reference_date: date | None = None) -> date:
        """获取最近一个已完成的交易日。"""
        if reference_date is None:
            reference_date = date.today()

        # 往前推 10 天，确保能找到至少一个交易日
        start_date = reference_date - timedelta(days=10)
        trade_dates = self.get_trade_dates(start_date, reference_date)

        if not trade_dates:
            raise ServiceError(
                code="gm.no_trade_dates",
                message="未找到交易日",
                retryable=False,
                context={"reference_date": str(reference_date)},
            )

        # 返回最近的交易日（小于等于 reference_date）
        valid_dates = [d for d in trade_dates if d <= reference_date]
        if not valid_dates:
            raise ServiceError(
                code="gm.no_valid_trade_date",
                message="未找到有效交易日",
                retryable=False,
                context={"reference_date": str(reference_date)},
            )

        return max(valid_dates)

    def get_trade_date_n_years_ago(self, years: int, reference_date: date | None = None) -> date:
        """获取 N 年前的交易日（用于三年回补）。"""
        if reference_date is None:
            reference_date = date.today()

        # 简单估算：N 年前的日期
        approx_date = date(reference_date.year - years, reference_date.month, reference_date.day)

        # 往前推 30 天，确保能找到交易日
        start_date = approx_date - timedelta(days=30)
        end_date = approx_date + timedelta(days=30)

        trade_dates = self.get_trade_dates(start_date, end_date)
        if not trade_dates:
            raise ServiceError(
                code="gm.no_trade_dates",
                message=f"未找到 {years} 年前的交易日",
                retryable=False,
                context={"reference_date": str(reference_date), "years": years},
            )

        # 返回最接近 approx_date 的交易日
        return min(trade_dates, key=lambda d: abs((d - approx_date).days))

    def get_next_trade_date(self, current_date: date) -> date:
        """获取下一个交易日。"""
        # 往后推 10 天，确保能找到下一个交易日
        end_date = current_date + timedelta(days=10)
        trade_dates = self.get_trade_dates(current_date, end_date)

        valid_dates = [d for d in trade_dates if d > current_date]
        if not valid_dates:
            raise ServiceError(
                code="gm.no_next_trade_date",
                message="未找到下一个交易日",
                retryable=False,
                context={"current_date": str(current_date)},
            )

        return min(valid_dates)
