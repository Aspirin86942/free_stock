from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from gmtrade_live.config import load_config
from gmtrade_live.gateways.gm_market_gateway import GMCurrentQuoteGateway
from gmtrade_live.gateways.gmtrade_trade_gateway import GMTradeQueryGateway
from gmtrade_live.logging_setup import setup_logging
from gmtrade_live.services.m0_connectivity import ConnectivityCheckService
from gmtrade_live.session import resolve_trading_session


def run_m0_connectivity_check(config_path: Path) -> int:
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
