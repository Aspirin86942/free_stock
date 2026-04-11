"""M2 dry-run 编排服务。"""

from __future__ import annotations

from datetime import datetime
import logging
from time import perf_counter
from zoneinfo import ZoneInfo

from gmtrade_live.config import AppConfig
from gmtrade_live.models import (
    DecisionLifecycleState,
    DecisionResult,
    EvaluatedSymbol,
    M2ChangeEvent,
    M2RoundReport,
    M2RoundSummary,
)
from gmtrade_live.session import resolve_trading_session


class M2DryRunService:
    """负责单轮 M2 dry-run 的持仓、行情与决策编排。"""

    def __init__(
        self,
        *,
        trade_gateway,
        market_gateway,
        state_manager,
        decision_engine,
        logger: logging.Logger,
        clock=None,
        timer=None,
    ) -> None:
        self._trade_gateway = trade_gateway
        self._market_gateway = market_gateway
        self._state_manager = state_manager
        self._decision_engine = decision_engine
        self._logger = logger
        self._clock = clock or (lambda: datetime.now(tz=ZoneInfo("Asia/Shanghai")))
        self._timer = timer or perf_counter
        self._last_decisions: dict[str, DecisionResult] = {}

    def run_round(self, *, config: AppConfig, round_no: int) -> M2RoundReport:
        """执行单轮 M2 dry-run。"""
        started_at = self._timer()
        now = self._clock()
        session_state = resolve_trading_session(
            now,
            timezone_name=config.timezone,
            market_session_mode=config.market_session_mode,
        )
        # 获取当前持仓
        positions = tuple(
            position
            for position in self._trade_gateway.get_positions(config.account_id)
            if position.volume > 0
        )
        # 同步持仓到状态管理器，并生成持仓变化事件。
        before_states = {
            state.symbol: state for state in self._state_manager.active_states()
        }
        self._state_manager.sync_positions(positions=positions, now=now)
        active_states = {
            state.symbol: state for state in self._state_manager.active_states()
        }
        # 获取持仓对应的行情，并生成决策结果与决策变化事件。
        symbols = [position.symbol for position in positions]
        quotes = tuple(self._market_gateway.get_quotes(symbols)) if symbols else ()
        quote_map = {quote.symbol: quote for quote in quotes}

        change_events: list[M2ChangeEvent] = []
        evaluated_symbols: list[EvaluatedSymbol] = []
        # 处理“状态变化”，比如新开始关注、进入墓碑状态
        for symbol, snapshot in active_states.items():
            previous = before_states.get(symbol)
            if previous is None:
                change_events.append(
                    M2ChangeEvent(
                        symbol=symbol,
                        change_tags=("symbol_started_watching",),
                        decision=None,
                        state_snapshot=snapshot,
                    )
                )
            elif (
                previous.lifecycle_state is not DecisionLifecycleState.tombstone
                and snapshot.lifecycle_state is DecisionLifecycleState.tombstone
            ):
                # 先把持仓消失写成显式变化事件，是为了后续状态表能直接消费这一轮事实。
                change_events.append(
                    M2ChangeEvent(
                        symbol=symbol,
                        change_tags=("entered_tombstone",),
                        decision=None,
                        state_snapshot=snapshot,
                    )
                )
        # 逐只持仓做决策判断
        for position in positions:

            # 取出该股票的状态，并调用决策引擎
            state_snapshot = active_states[position.symbol]
            decision = self._decision_engine.evaluate(
                position=position,
                quote=quote_map.get(position.symbol),
                session_state=session_state,
                state_snapshot=state_snapshot,
                config=config,
                now=now,
            )

            # 把决策结果反馈回状态管理器
            updated_state = self._state_manager.update_decision_feedback(
                position.symbol,
                trigger_reason=decision.trigger_reason,
                block_reason=decision.block_reason,
                volume=decision.volume,
                available_volume=decision.available_volume,
                sellable_now=decision.sellable_now,
                decision_time=decision.evaluated_at,
            )
            evaluated = EvaluatedSymbol(decision=decision, state_snapshot=updated_state)
            evaluated_symbols.append(evaluated)
            # 拿上一轮结果，判断这一轮有没有变化
            previous_decision = self._last_decisions.get(position.symbol)
            change_tags: list[str] = []

            # 如果以前没有记录，这一轮一上来就满足卖出条件，形成触发条件；
            # 如果上一轮和这一轮 should_sell 不一样：这轮变成该卖 -> trigger_activated这轮变成不该卖 -> trigger_cleared

            if previous_decision is None and decision.should_sell:
                change_tags.append("trigger_activated")
            elif (
                previous_decision is not None
                and previous_decision.should_sell != decision.should_sell
            ):
                change_tags.append(
                    "trigger_activated" if decision.should_sell else "trigger_cleared"
                )

            # 判断“是否允许提交卖单”有没有变化

            if (
                previous_decision is not None
                and previous_decision.can_submit_sell != decision.can_submit_sell
            ):
                change_tags.append(
                    "submit_permission_granted"
                    if decision.can_submit_sell
                    else "submit_permission_blocked"
                )

            # 判断“被阻塞的原因”有没有变化

            if (
                previous_decision is not None
                and previous_decision.block_reason != decision.block_reason
            ):
                if decision.block_reason == "quote_missing":
                    change_tags.append("quote_missing_detected")
                elif previous_decision.block_reason == "quote_missing":
                    change_tags.append("quote_missing_recovered")
            if change_tags:
                change_events.append(
                    M2ChangeEvent(
                        symbol=position.symbol,
                        change_tags=tuple(change_tags),
                        decision=decision,
                        state_snapshot=updated_state,
                    )
                )
            self._last_decisions[position.symbol] = decision

        tombstones = tuple(
            state
            for state in self._state_manager.active_states()
            if state.lifecycle_state is DecisionLifecycleState.tombstone
        )
        duration_ms = int((self._timer() - started_at) * 1000)
        return M2RoundReport(
            summary=M2RoundSummary(
                round_no=round_no,
                session_state=session_state.value,
                position_count=len(positions),
                watching_count=len(evaluated_symbols),
                tombstone_count=len(tombstones),
                should_sell_count=sum(
                    1 for item in evaluated_symbols if item.decision.should_sell
                ),
                can_submit_sell_count=sum(
                    1 for item in evaluated_symbols if item.decision.can_submit_sell
                ),
                changed_symbol_count=len({event.symbol for event in change_events}),
                duration_ms=duration_ms,
            ),
            evaluated_symbols=tuple(evaluated_symbols),
            tombstones=tombstones,
            change_events=tuple(change_events),
        )
