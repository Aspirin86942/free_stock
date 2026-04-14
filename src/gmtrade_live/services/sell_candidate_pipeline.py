"""卖出候选标的共享评估管线。

职责边界：
- 读取持仓、读取行情
- 同步决策状态
- 生成卖出决策与变化事件汇总

明确不做：
- 不发单、不提交委托（执行层负责）
"""

from __future__ import annotations

import logging
from datetime import datetime
from time import perf_counter
from zoneinfo import ZoneInfo

from gmtrade_live.config import AppConfig
from gmtrade_live.gateways.protocols import MarketGateway, TradeGateway
from gmtrade_live.models import (
    CandidateRound,
    CandidateRoundSummary,
    DecisionChangeEvent,
    DecisionLifecycleState,
    DecisionResult,
    SellCandidate,
)
from gmtrade_live.session import resolve_trading_session


class SellCandidatePipeline:
    """共享评估管线：把“拉取 + 决策 + 变化检测”收敛到一个可复用入口。"""

    def __init__(
        self,
        *,
        trade_gateway: TradeGateway,
        market_gateway: MarketGateway,
        state_store,
        decision_engine,
        logger: logging.Logger,
        clock=None,
        timer=None,
    ) -> None:
        self._trade_gateway = trade_gateway
        self._market_gateway = market_gateway
        self._state_store = state_store
        self._decision_engine = decision_engine
        self._logger = logger
        self._clock = clock or (lambda: datetime.now(tz=ZoneInfo("Asia/Shanghai")))
        self._timer = timer or perf_counter
        self._last_decisions: dict[str, DecisionResult] = {}

    def run_round(self, *, config: AppConfig, round_no: int) -> CandidateRound:
        """执行单轮“候选卖出标的”评估。"""
        started_at = self._timer()
        now = self._clock()
        session_state = resolve_trading_session(
            now,
            timezone_name=config.timezone,
            market_session_mode=config.market_session_mode,
        )

        # 获取当前持仓，只保留真正有仓位的行，避免“空仓行”触发无意义的评估。
        positions = tuple(
            position
            for position in self._trade_gateway.get_positions(config.account_id)
            if position.volume > 0
        )

        # 同步持仓到状态存储，并在同步前后对比生成“状态变化事件”（如开始关注/进入墓碑）。
        before_states = {state.symbol: state for state in self._state_store.active_states()}
        self._state_store.sync_positions(positions=positions, now=now)
        active_states = {state.symbol: state for state in self._state_store.active_states()}

        symbols = [position.symbol for position in positions]
        quotes = tuple(self._market_gateway.get_quotes(symbols)) if symbols else ()
        quote_map = {quote.symbol: quote for quote in quotes}

        change_events: list[DecisionChangeEvent] = []
        candidates: list[SellCandidate] = []

        for symbol, snapshot in active_states.items():
            previous = before_states.get(symbol)
            if previous is None:
                change_events.append(
                    DecisionChangeEvent(
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
                # 先把持仓消失写成显式变化事件，是为了让审计/观测服务能稳定输出这一轮事实。
                change_events.append(
                    DecisionChangeEvent(
                        symbol=symbol,
                        change_tags=("entered_tombstone",),
                        decision=None,
                        state_snapshot=snapshot,
                    )
                )

        for position in positions:
            state_snapshot = active_states[position.symbol]
            decision = self._decision_engine.evaluate(
                position=position,
                quote=quote_map.get(position.symbol),
                session_state=session_state,
                state_snapshot=state_snapshot,
                config=config,
                now=now,
            )

            updated_state = self._state_store.update_decision_feedback(
                position.symbol,
                trigger_reason=decision.trigger_reason,
                block_reason=decision.block_reason,
                volume=decision.volume,
                available_volume=decision.available_volume,
                sellable_now=decision.sellable_now,
                decision_time=decision.evaluated_at,
            )
            candidates.append(SellCandidate(decision=decision, state_snapshot=updated_state))

            previous_decision = self._last_decisions.get(position.symbol)
            change_tags: list[str] = []

            if previous_decision is None and decision.should_sell:
                change_tags.append("trigger_activated")
            elif (
                previous_decision is not None
                and previous_decision.should_sell != decision.should_sell
            ):
                change_tags.append(
                    "trigger_activated" if decision.should_sell else "trigger_cleared"
                )

            if (
                previous_decision is not None
                and previous_decision.can_submit_sell != decision.can_submit_sell
            ):
                change_tags.append(
                    "submit_permission_granted"
                    if decision.can_submit_sell
                    else "submit_permission_blocked"
                )

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
                    DecisionChangeEvent(
                        symbol=position.symbol,
                        change_tags=tuple(change_tags),
                        decision=decision,
                        state_snapshot=updated_state,
                    )
                )

            self._last_decisions[position.symbol] = decision

        tombstones = tuple(
            state
            for state in self._state_store.active_states()
            if state.lifecycle_state is DecisionLifecycleState.tombstone
        )
        duration_ms = int((self._timer() - started_at) * 1000)

        # 日志保留入口，但不在这里写大量“业务日志”，避免把观测管线变成执行层。
        self._logger.debug(
            "sell_candidate_pipeline_round_completed",
            extra={
                "round_no": round_no,
                "position_count": len(positions),
                "candidate_count": len(candidates),
                "tombstone_count": len(tombstones),
                "change_symbol_count": len({event.symbol for event in change_events}),
                "duration_ms": duration_ms,
            },
        )

        summary = CandidateRoundSummary(
            round_no=round_no,
            session_state=session_state.value,
            position_count=len(positions),
            watching_count=len(candidates),
            tombstone_count=len(tombstones),
            should_sell_count=sum(1 for item in candidates if item.decision.should_sell),
            can_submit_sell_count=sum(
                1 for item in candidates if item.decision.can_submit_sell
            ),
            changed_symbol_count=len({event.symbol for event in change_events}),
            duration_ms=duration_ms,
        )
        return CandidateRound(
            summary=summary,
            candidates=tuple(candidates),
            tombstones=tombstones,
            change_events=tuple(change_events),
        )
