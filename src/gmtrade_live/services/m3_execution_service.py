"""M3 执行服务兼容层。

兼容目标：
1. 保留旧构造参数（market_gateway / decision_state_manager / decision_engine）。
2. 内部仍走 Task 2 的共享候选结果链路（SellCandidatePipeline -> AutoSellService）。
"""

from __future__ import annotations

import logging

from gmtrade_live.gateways.protocols import MarketGateway, TradeGateway
from gmtrade_live.services.auto_sell_service import AutoSellService
from gmtrade_live.services.order_execution_state import OrderExecutionStateStore
from gmtrade_live.services.sell_candidate_pipeline import SellCandidatePipeline


class M3ExecutionService(AutoSellService):
    """旧 API 形态的自动卖出服务适配器。"""

    def __init__(
        self,
        *,
        trade_gateway: TradeGateway,
        execution_state_manager: OrderExecutionStateStore,
        logger: logging.Logger,
        audit_logger: logging.Logger | None = None,
        market_gateway: MarketGateway | None = None,
        decision_state_manager=None,
        decision_engine=None,
        candidate_pipeline=None,
        clock=None,
        timer=None,
        sleep=None,
    ) -> None:
        resolved_pipeline = candidate_pipeline
        if resolved_pipeline is None:
            missing: list[str] = []
            if market_gateway is None:
                missing.append("market_gateway")
            if decision_state_manager is None:
                missing.append("decision_state_manager")
            if decision_engine is None:
                missing.append("decision_engine")
            if missing:
                missing_text = ", ".join(missing)
                raise TypeError(
                    "M3ExecutionService missing required arguments for compatibility path: "
                    f"{missing_text}"
                )

            # 兼容构造下在这里统一生成共享候选管线，确保旧调用方也进入 Task 2 执行链。
            resolved_pipeline = SellCandidatePipeline(
                trade_gateway=trade_gateway,
                market_gateway=market_gateway,
                state_store=decision_state_manager,
                decision_engine=decision_engine,
                logger=logger,
                clock=clock,
                timer=timer,
            )

        super().__init__(
            trade_gateway=trade_gateway,
            candidate_pipeline=resolved_pipeline,
            execution_state_manager=execution_state_manager,
            logger=logger,
            audit_logger=audit_logger,
            clock=clock,
            timer=timer,
            sleep=sleep,
        )


__all__ = ["AutoSellService", "M3ExecutionService"]
