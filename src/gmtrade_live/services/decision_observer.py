"""决策观测服务。

该服务用于 dry-run/观测场景：输出本轮候选卖出标的、墓碑状态与变化事件。
它必须消费共享评估管线的输出，避免重复拉取持仓/行情并产生分叉行为。
"""

from __future__ import annotations

import logging

from gmtrade_live.config import AppConfig
from gmtrade_live.models import CandidateRound, DecisionObservationReport, DecisionRoundSummary


class DecisionObserverService:
    """对外提供“单轮决策观测”能力。"""

    def __init__(
        self,
        *,
        pipeline,
        logger: logging.Logger,
    ) -> None:
        self._pipeline = pipeline
        self._logger = logger

    def run_round(self, *, config: AppConfig, round_no: int) -> DecisionObservationReport:
        """执行单轮观测。

        为什么这里只做委托：
        - 观测语义应与执行语义共享同一评估结果，避免“观测能看到、执行却算不出来”的差异。
        """
        result: CandidateRound = self._pipeline.run_round(config=config, round_no=round_no)
        summary = DecisionRoundSummary(
            round_no=result.summary.round_no,
            session_state=result.summary.session_state,
            position_count=result.summary.position_count,
            watching_count=result.summary.watching_count,
            tombstone_count=result.summary.tombstone_count,
            should_sell_count=result.summary.should_sell_count,
            can_submit_sell_count=result.summary.can_submit_sell_count,
            changed_symbol_count=result.summary.changed_symbol_count,
            duration_ms=result.summary.duration_ms,
        )
        report = DecisionObservationReport(
            summary=summary,
            candidates=result.candidates,
            tombstones=result.tombstones,
            change_events=result.change_events,
        )
        self._logger.debug(
            "decision_observer_round_completed",
            extra={"round_no": round_no, "position_count": report.summary.position_count},
        )
        return report
