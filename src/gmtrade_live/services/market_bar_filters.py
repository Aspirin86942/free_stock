"""市场分析行情行过滤 helper。"""

from __future__ import annotations

import logging
from decimal import Decimal

from gmtrade_live.market_models import DailyBar


def is_tradable_bar(bar: DailyBar) -> bool:
    """判断行情行是否代表可交易样本。"""
    return bar.has_trade and not bar.suspended


def is_price_calculable_bar(bar: DailyBar) -> bool:
    """判断行情行是否可安全计算涨跌幅。"""
    return (
        is_tradable_bar(bar)
        and bar.close is not None
        and bar.pre_close is not None
        and bar.pre_close > Decimal("0")
    )


def is_valid_return_bar(bar: DailyBar | None) -> bool:
    """判断行情行是否可作为收益率计算端点。"""
    return (
        bar is not None
        and is_tradable_bar(bar)
        and bar.close is not None
        and bar.close > Decimal("0")
    )


def filter_tradable_bars(bars: list[DailyBar]) -> list[DailyBar]:
    """第一层过滤：只保留正常交易样本，不把停牌/无交易视为脏数据。"""
    return [bar for bar in bars if is_tradable_bar(bar)]


def filter_price_calculable_bars(
    bars: list[DailyBar],
    *,
    logger: logging.Logger,
    context: str,
) -> list[DailyBar]:
    """第二层过滤：跳过无法计算涨跌幅的单行脏数据并写审计日志。"""
    valid_bars: list[DailyBar] = []
    for bar in bars:
        if is_price_calculable_bar(bar):
            valid_bars.append(bar)
            continue

        # 为什么这里只记录 tradable 样本：停牌/无交易是正常市场状态，不应混入脏数据审计。
        if is_tradable_bar(bar):
            logger.warning(
                "invalid_price_bar_skipped context=%s symbol=%s trade_date=%s close=%s pre_close=%s reason=pre_close_not_positive",
                context,
                bar.symbol,
                bar.trade_date,
                bar.close,
                bar.pre_close,
            )
    return valid_bars


__all__ = [
    "filter_price_calculable_bars",
    "filter_tradable_bars",
    "is_price_calculable_bar",
    "is_tradable_bar",
    "is_valid_return_bar",
]
