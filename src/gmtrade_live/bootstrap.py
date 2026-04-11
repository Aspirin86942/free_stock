"""应用启动层，负责拼装依赖并输出命令行结果。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
import time
from zoneinfo import ZoneInfo

from gmtrade_live.config import load_config
from gmtrade_live.gateways.gm_market_gateway import GMCurrentQuoteGateway
from gmtrade_live.gateways.gmtrade_trade_gateway import GMTradeGateway
from gmtrade_live.logging_setup import setup_logging
from gmtrade_live.services.m0_connectivity import ConnectivityCheckService
from gmtrade_live.services.m1_manual_trade import ManualTradeService
from gmtrade_live.services.m2_decision_engine import M2DecisionEngine
from gmtrade_live.services.m2_dry_run import M2DryRunService
from gmtrade_live.services.m2_state_manager import M2StateManager
from gmtrade_live.services.m3_execution_service import M3ExecutionService
from gmtrade_live.session import resolve_trading_session
from gmtrade_live.state import PositionStateManager


def _resolve_current_session_state(config) -> object:
    """统一校验市场时段模式；未实现模式应在所有入口一致拦截。"""
    return resolve_trading_session(
        datetime.now(tz=ZoneInfo(config.timezone)),
        timezone_name=config.timezone,
        market_session_mode=config.market_session_mode,
    )


def run_m0_connectivity_check(config_path: Path) -> int:
    """执行 M0 连通性检查并输出精简 JSON 摘要。"""
    config = load_config(config_path)
    logger = setup_logging(config.strategy_name, config.log_dir)

    logger.info("heartbeat round=1 status=starting config=%s", config_path)

    session_state = _resolve_current_session_state(config)

    service = ConnectivityCheckService(
        trade_gateway=GMTradeGateway(),
        market_gateway=GMCurrentQuoteGateway(),
        logger=logger,
    )
    report = service.run(config=config, session_state=session_state)

    print(
        json.dumps(
            {
                "account_id": report.account_id,
                "session_state": report.session_state,
                "available_cash": str(report.cash.available_cash),
                "position_count": len(report.positions),
                "quote_count": len(report.quotes),
            },
            ensure_ascii=False,
        )
    )

    logger.info(
        "heartbeat round=1 status=completed positions=%s quotes=%s",
        len(report.positions),
        len(report.quotes),
    )
    return 0


def run_m1_manual_trade(
    *,
    config_path: Path,
    symbol: str,
    volume: int,
    price_type: str,
    price: Decimal | None,
    timeout_seconds: int,
    side: str,
) -> int:
    """执行 M1 手工交易验证并输出最终交易报告。"""
    config = load_config(config_path)
    _resolve_current_session_state(config)
    logger = setup_logging(config.strategy_name, config.log_dir)
    gateway = GMTradeGateway(account_id=config.account_id)

    gateway.connect(config)

    service = ManualTradeService(
        trade_gateway=gateway,
        logger=logger,
    )
    report = service.run(
        config=config,
        symbol=symbol,
        volume=volume,
        price_type=price_type,
        price=price,
        timeout_seconds=timeout_seconds,
        side=side,
    )

    # CLI 只打印结构化 JSON，便于人工查看和脚本消费共用同一输出。
    print(
        json.dumps(
            {
                "verification_passed": report.verification_passed,
                "side": report.side,
                "cl_ord_id": report.cl_ord_id,
                "broker_order_id": report.broker_order_id,
                "submit_accepted": report.submit_accepted,
                "order_status_confirmed": report.order_status_confirmed,
                "execution_status_confirmed": report.execution_status_confirmed,
                "last_order_status": report.last_order_status,
                "rejection_reason": report.rejection_reason,
                "filled_volume": report.filled_volume,
                "avg_price": (
                    str(report.avg_price) if report.avg_price is not None else None
                ),
                "message": report.message,
            },
            ensure_ascii=False,
        )
    )
    return 0 if report.verification_passed else 1


def run_m2_dry_run(
    *,
    config_path: Path,
    once: bool,
    max_rounds: int | None,
) -> int:
    """执行 M2 决策 dry-run 并输出结构化结果。"""
    config = load_config(config_path)
    _resolve_current_session_state(config)
    logger = setup_logging(config.strategy_name, config.log_dir)
    trade_gateway = GMTradeGateway()
    market_gateway = GMCurrentQuoteGateway()

    trade_gateway.connect(config)
    market_gateway.connect(config.token)

    service = M2DryRunService(
        trade_gateway=trade_gateway,
        market_gateway=market_gateway,
        state_manager=M2StateManager(logger),
        decision_engine=M2DecisionEngine(),
        logger=logger,
    )

    round_no = 1
    while True:
        try:
            report = service.run_round(config=config, round_no=round_no)
        except Exception as exc:
            logger.error(
                "m2_round_failed round=%s error_type=%s error=%s",
                round_no,
                type(exc).__name__,
                str(exc),
                exc_info=True,
            )
            print(
                json.dumps(
                    {
                        "kind": "m2_round_error",
                        "round": round_no,
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    },
                    ensure_ascii=False,
                )
            )
            if once or (max_rounds is not None and round_no >= max_rounds):
                return 1
        else:
            print(
                json.dumps(
                    {
                        "kind": "m2_round_summary",
                        "round": report.summary.round_no,
                        "session_state": report.summary.session_state,
                        "position_count": report.summary.position_count,
                        "watching_count": report.summary.watching_count,
                        "tombstone_count": report.summary.tombstone_count,
                        "should_sell_count": report.summary.should_sell_count,
                        "can_submit_sell_count": report.summary.can_submit_sell_count,
                        "changed_symbol_count": report.summary.changed_symbol_count,
                        "duration_ms": report.summary.duration_ms,
                    },
                    ensure_ascii=False,
                )
            )
            for event in report.change_events:
                lifecycle_state = None
                if event.state_snapshot is not None:
                    lifecycle_state = getattr(
                        event.state_snapshot.lifecycle_state,
                        "value",
                        event.state_snapshot.lifecycle_state,
                    )
                payload = {
                    "kind": "m2_change_detail",
                    "symbol": event.symbol,
                    "change_tags": list(event.change_tags),
                    "lifecycle_state": lifecycle_state,
                    "volume": (
                        event.state_snapshot.volume
                        if event.state_snapshot is not None
                        else None
                    ),
                    "available_volume": (
                        event.state_snapshot.available_volume
                        if event.state_snapshot is not None
                        else None
                    ),
                    "sellable_now": (
                        event.state_snapshot.sellable_now
                        if event.state_snapshot is not None
                        else None
                    ),
                }
                if event.decision is not None:
                    payload.update(
                        {
                            "should_sell": event.decision.should_sell,
                            "can_submit_sell": event.decision.can_submit_sell,
                            "trigger_reason": event.decision.trigger_reason,
                            "block_reason": event.decision.block_reason,
                            "current_price": str(event.decision.current_price),
                            "session_state": event.decision.session_state,
                            "evaluated_at": event.decision.evaluated_at.isoformat(),
                        }
                    )
                print(json.dumps(payload, ensure_ascii=False))

            if once or (max_rounds is not None and round_no >= max_rounds):
                return 0
            if report.summary.duration_ms > config.poll_interval_seconds * 1000:
                logger.warning(
                    "round_overrun round=%s duration_ms=%s interval_seconds=%s",
                    round_no,
                    report.summary.duration_ms,
                    config.poll_interval_seconds,
                )
        time.sleep(config.poll_interval_seconds)
        round_no += 1


def run_m3_execution(
    *,
    config_path: Path,
    once: bool,
    max_rounds: int | None,
) -> int:
    """执行 M3 自动卖出闭环并输出结构化结果。"""
    config = load_config(config_path)
    _resolve_current_session_state(config)
    logger = setup_logging(config.strategy_name, config.log_dir)
    trade_gateway = GMTradeGateway()
    market_gateway = GMCurrentQuoteGateway()

    trade_gateway.connect(config)
    market_gateway.connect(config.token)

    service = M3ExecutionService(
        trade_gateway=trade_gateway,
        market_gateway=market_gateway,
        state_manager=PositionStateManager(logger),
        decision_engine=M2DecisionEngine(),
        logger=logger,
    )

    round_no = 1
    while True:
        try:
            report = service.run_round(config=config, round_no=round_no)
        except Exception as exc:
            # M3 是真实执行链路，单轮异常直接中止，避免在不确定状态下继续发单。
            logger.error(
                "m3_round_failed round=%s error_type=%s error=%s",
                round_no,
                type(exc).__name__,
                str(exc),
                exc_info=True,
            )
            print(
                json.dumps(
                    {
                        "kind": "m3_round_error",
                        "round": round_no,
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    },
                    ensure_ascii=False,
                )
            )
            return 1

        print(
            json.dumps(
                {
                    "kind": "m3_round_summary",
                    "round": report.summary.round_no,
                    "session_state": report.summary.session_state,
                    "position_count": report.summary.position_count,
                    "candidate_count": report.summary.candidate_count,
                    "blocked_count": report.summary.blocked_count,
                    "submitted_count": report.summary.submitted_count,
                    "open_order_count": report.summary.open_order_count,
                    "changed_symbol_count": report.summary.changed_symbol_count,
                    "duration_ms": report.summary.duration_ms,
                },
                ensure_ascii=False,
            )
        )
        for block in report.block_details:
            print(
                json.dumps(
                    {
                        "kind": "m3_block_detail",
                        "symbol": block.symbol,
                        "trigger_reason": block.trigger_reason,
                        "requested_ratio": str(block.requested_ratio),
                        "total_volume": block.total_volume,
                        "available_volume": block.available_volume,
                        "raw_target_volume": block.raw_target_volume,
                        "promotion_type": block.promotion_type,
                        "normalized_target_volume": block.normalized_target_volume,
                        "block_reason": block.block_reason,
                        "evaluated_at": block.evaluated_at.isoformat(),
                    },
                    ensure_ascii=False,
                )
            )
        for detail in report.execution_details:
            print(
                json.dumps(
                    {
                        "kind": "m3_execution_detail",
                        "symbol": detail.symbol,
                        "change_tags": list(detail.change_tags),
                        "execution_state": detail.execution_state,
                        "cl_ord_id": detail.cl_ord_id,
                        "broker_order_id": detail.broker_order_id,
                        "requested_volume": detail.requested_volume,
                        "filled_volume": detail.filled_volume,
                        "remaining_volume": detail.remaining_volume,
                        "submit_accepted": detail.submit_accepted,
                        "last_order_status": detail.last_order_status,
                        "rejection_reason": detail.rejection_reason,
                        "avg_price": (
                            str(detail.avg_price)
                            if detail.avg_price is not None
                            else None
                        ),
                        "event_time": detail.event_time.isoformat(),
                        "message": detail.message,
                    },
                    ensure_ascii=False,
                )
            )

        if once or (max_rounds is not None and round_no >= max_rounds):
            return 0
        if report.summary.duration_ms > config.poll_interval_seconds * 1000:
            logger.warning(
                "round_overrun round=%s duration_ms=%s interval_seconds=%s",
                round_no,
                report.summary.duration_ms,
                config.poll_interval_seconds,
            )
        time.sleep(config.poll_interval_seconds)
        round_no += 1
