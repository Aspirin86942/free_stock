"""M2 单标的决策判断。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from gmtrade_live.config import AppConfig
from gmtrade_live.models import (
    DecisionPositionStateSnapshot,
    DecisionResult,
    PositionSnapshot,
    QuoteSnapshot,
)
from gmtrade_live.precision import normalize_price
from gmtrade_live.session import TradingSessionState


class M2DecisionEngine:
    """负责按单标的生成 M2 决策结果。"""

    def evaluate(
        self,
        *,
        position: PositionSnapshot,
        quote: QuoteSnapshot | None,
        session_state: TradingSessionState,
        state_snapshot: DecisionPositionStateSnapshot,
        config: AppConfig,
        now: datetime,
    ) -> DecisionResult:
        """评估当前标的的应卖结论与可提交结论。"""
        del state_snapshot

        cost_price = normalize_price(position.cost_price)
        take_profit_price = normalize_price(
            cost_price * (Decimal("1") + config.take_profit_ratio)
        )
        stop_loss_price = normalize_price(
            cost_price * (Decimal("1") - config.stop_loss_ratio)
        )

        if quote is None:
            return DecisionResult(
                symbol=position.symbol,
                should_sell=False,
                can_submit_sell=False,
                trigger_reason=None,
                block_reason="quote_missing",
                current_price=Decimal("0"),
                cost_price=cost_price,
                take_profit_price=take_profit_price,
                stop_loss_price=stop_loss_price,
                volume=position.volume,
                available_volume=position.available_volume,
                sellable_now=position.available_volume > 0,
                session_state=session_state.value,
                evaluated_at=now,
            )

        current_price = normalize_price(quote.last_price)
        should_sell = False
        trigger_reason: str | None = None

        if current_price >= take_profit_price:
            should_sell = True
            trigger_reason = "take_profit_triggered"
        elif current_price <= stop_loss_price:
            should_sell = True
            trigger_reason = "stop_loss_triggered"

        sellable_now = position.available_volume > 0
        can_submit_sell = False
        block_reason: str | None = None

        # 这里先把策略触发和可执行性拆开，是为了后续执行层能直接消费决策事实。
        if not should_sell:
            block_reason = "price_not_reached"
        # elif session_state is not TradingSessionState.TRADING:
        #     block_reason = "not_in_trading_session"
        elif not sellable_now:
            block_reason = "temporarily_not_closable"
        else:
            can_submit_sell = True

        return DecisionResult(
            symbol=position.symbol,
            should_sell=should_sell,
            can_submit_sell=can_submit_sell,
            trigger_reason=trigger_reason,
            block_reason=block_reason,
            current_price=current_price,
            cost_price=cost_price,
            take_profit_price=take_profit_price,
            stop_loss_price=stop_loss_price,
            volume=position.volume,
            available_volume=position.available_volume,
            sellable_now=sellable_now,
            session_state=session_state.value,
            evaluated_at=now,
        )
