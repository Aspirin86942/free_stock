"""市场分析链路的数据模型。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class SecurityMaster:
    """股票池静态属性。"""

    symbol: str
    exchange: str
    name: str
    board: str
    listed_date: date


@dataclass(frozen=True, slots=True)
class DailyBar:
    """日线行情数据。"""

    symbol: str
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    pre_close: Decimal
    volume: int
    amount: Decimal
    turnover_rate: Decimal | None
    is_st: bool
    suspended: bool
    has_trade: bool


@dataclass(frozen=True, slots=True)
class SyncCheckpoint:
    """同步检查点。"""

    job_name: str
    last_success_trade_date: date
    updated_at: str


@dataclass(frozen=True, slots=True)
class MarketBreadthMetrics:
    """市场宽度指标。"""

    up_count: int
    down_count: int
    up_ratio: Decimal
    total_amount: Decimal
    limit_up_count: int
    limit_down_count: int
    new_high_20d_count: int
    new_low_20d_count: int
    new_high_60d_count: int
    new_low_60d_count: int


@dataclass(frozen=True, slots=True)
class ProfitEffectMetrics:
    """赚钱效应指标。"""

    limit_up_yesterday_avg_return: Decimal | None
    consecutive_limit_up_yesterday_avg_return: Decimal | None
    hot_stock_4d_avg_return: Decimal | None


@dataclass(frozen=True, slots=True)
class ToleranceMetrics:
    """容错指标。"""

    st_count: int
    delisting_risk_count: int
    broken_limit_up_yesterday_avg_return: Decimal | None
    hot_stock_close_above_avg_price_ratio: Decimal | None
    hot_stock_max_drawdown_median: Decimal | None


@dataclass(frozen=True, slots=True)
class EmotionMetrics:
    """情绪指标。"""

    pct_above_9_5_count: int
    pct_below_minus_9_5_count: int
    broken_limit_up_ratio: Decimal | None
    pct_above_30_in_3d_count: int


@dataclass(frozen=True, slots=True)
class DailyReportRow:
    """单日报告行（汇总所有指标）。"""

    trade_date: date
    breadth: MarketBreadthMetrics
    profit_effect: ProfitEffectMetrics
    tolerance: ToleranceMetrics
    emotion: EmotionMetrics


@dataclass(frozen=True, slots=True)
class MarketCloseReport:
    """盘后市场分析报告。"""

    report_trade_date: date
    summary: str
    daily_rows: list[DailyReportRow]
    data_quality_flags: tuple[str, ...] = ()
