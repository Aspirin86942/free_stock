"""M0 连通性调试脚本，仅用于排障验证。"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from gmtrade_live.config import AppConfig, load_config
from gmtrade_live.gateways.gm_market_gateway import GMCurrentQuoteGateway
from gmtrade_live.gateways.gmtrade_trade_gateway import GMTradeGateway
from gmtrade_live.gateways.protocols import MarketGateway, TradeGateway
from gmtrade_live.logging_setup import setup_logging
from gmtrade_live.models import ConnectivityReport
from gmtrade_live.session import TradingSessionState, resolve_trading_session


def build_connectivity_summary(report: ConnectivityReport) -> dict[str, object]:
    """生成 M0 JSON 摘要。"""
    return {
        "account_id": report.account_id,
        "session_state": report.session_state,
        "available_cash": str(report.cash.available_cash),
        "position_count": len(report.positions),
        "quote_count": len(report.quotes),
    }


def run_connectivity_check(
    *,
    config: AppConfig,
    session_state: TradingSessionState,
    trade_gateway: TradeGateway,
    market_gateway: MarketGateway,
    logger,
) -> ConnectivityReport:
    """执行一次 M0 连通性检查并返回报告。"""
    trade_gateway.connect(config)
    market_gateway.connect(config.token)

    cash = trade_gateway.get_cash(config.account_id)
    positions = trade_gateway.get_positions(config.account_id)
    # M0 只验证当前可卖持仓的行情连通性，避免把不可卖仓位也混入行情检查结果。
    symbols = [item.symbol for item in positions if item.available_volume > 0]
    quotes = market_gateway.get_quotes(symbols)

    logger.info(
        "m0_connectivity_success account_id=%s session_state=%s positions=%s quotes=%s",
        config.account_id,
        session_state.value,
        len(positions),
        len(quotes),
    )

    return ConnectivityReport(
        account_id=config.account_id,
        session_state=session_state.value,
        cash=cash,
        positions=tuple(positions),
        quotes=tuple(quotes),
    )


def _resolve_current_session_state(config: AppConfig) -> TradingSessionState:
    """统一校验市场时段模式；未实现模式应在所有入口一致拦截。"""
    return resolve_trading_session(
        datetime.now(tz=ZoneInfo(config.timezone)),
        timezone_name=config.timezone,
        market_session_mode=config.market_session_mode,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GMTrade connectivity debug check")
    parser.add_argument("--config", required=True, help="Path to YAML config file")
    return parser


def main(argv: list[str] | None = None) -> int:
    """调试入口，仅输出连通性摘要。"""
    args = _build_parser().parse_args(argv)
    config = load_config(Path(args.config))
    logger = setup_logging(config.strategy_name, config.log_dir)

    logger.info("debug_m0_connectivity_starting config=%s", args.config)

    session_state = _resolve_current_session_state(config)
    report = run_connectivity_check(
        config=config,
        session_state=session_state,
        trade_gateway=GMTradeGateway(),
        market_gateway=GMCurrentQuoteGateway(),
        logger=logger,
    )
    print(json.dumps(build_connectivity_summary(report), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
