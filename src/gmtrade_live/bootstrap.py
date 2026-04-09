"""应用启动层，负责拼装依赖并输出命令行结果。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from gmtrade_live.config import load_config
from gmtrade_live.gateways.gm_market_gateway import GMCurrentQuoteGateway
from gmtrade_live.gateways.gmtrade_trade_gateway import GMTradeQueryGateway
from gmtrade_live.logging_setup import setup_logging
from gmtrade_live.services.m0_connectivity import ConnectivityCheckService
from gmtrade_live.services.m1_manual_trade import ManualTradeService
from gmtrade_live.session import resolve_trading_session


def run_m0_connectivity_check(config_path: Path) -> int:
    """执行 M0 连通性检查并输出精简 JSON 摘要。"""
    config = load_config(config_path)
    logger = setup_logging(config.strategy_name, config.log_dir)

    logger.info("heartbeat round=1 status=starting config=%s", config_path)

    session_state = resolve_trading_session(
        datetime.now(tz=ZoneInfo(config.timezone)),
        start_text=config.trade_session_start,
        end_text=config.trade_session_end,
        timezone_name=config.timezone,
    )

    service = ConnectivityCheckService(
        trade_gateway=GMTradeQueryGateway(),
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
    logger = setup_logging(config.strategy_name, config.log_dir)
    gateway = GMTradeQueryGateway(account_id=config.account_id)

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
                "avg_price": str(report.avg_price) if report.avg_price is not None else None,
                "message": report.message,
            },
            ensure_ascii=False,
        )
    )
    return 0 if report.verification_passed else 1
