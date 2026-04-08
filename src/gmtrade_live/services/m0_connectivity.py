from __future__ import annotations

import logging

from gmtrade_live.config import AppConfig
from gmtrade_live.gateways.protocols import MarketGateway, TradeGateway
from gmtrade_live.models import ConnectivityReport
from gmtrade_live.session import TradingSessionState


class ConnectivityCheckService:
    def __init__(
        self,
        *,
        trade_gateway: TradeGateway,
        market_gateway: MarketGateway,
        logger: logging.Logger,
    ) -> None:
        self._trade_gateway = trade_gateway
        self._market_gateway = market_gateway
        self._logger = logger

    def run(
        self,
        *,
        config: AppConfig,
        session_state: TradingSessionState,
    ) -> ConnectivityReport:
        self._trade_gateway.connect(config)
        self._market_gateway.connect(config.token)

        cash = self._trade_gateway.get_cash(config.account_id)
        positions = self._trade_gateway.get_positions(config.account_id)
        # M0 只验证当前可卖持仓的行情连通性，避免把不可卖仓位也混入行情检查结果。
        symbols = [item.symbol for item in positions if item.available_volume > 0]
        quotes = self._market_gateway.get_quotes(symbols)

        self._logger.info(
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
