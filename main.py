"""项目命令行入口，负责解析 M0/M1 参数并分发执行。"""

from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Sequence


def _parse_positive_int(value: str) -> int:
    """把命令行整数参数解析为正数。"""
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("必须是整数") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("必须大于 0")
    return parsed


def _parse_positive_decimal(value: str) -> Decimal:
    """把命令行小数参数解析为正 Decimal。"""
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError("必须是合法小数") from exc
    if parsed <= Decimal("0"):
        raise argparse.ArgumentTypeError("必须大于 0")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    """构建项目统一 CLI 参数。"""
    parser = argparse.ArgumentParser(description="GMTrade connectivity and M1 manual trade")
    parser.add_argument("--config", required=True, help="Path to YAML config file")
    parser.add_argument("--mode", choices=("m0", "m1"), default="m0")
    parser.add_argument("--symbol")
    parser.add_argument("--volume", type=_parse_positive_int)
    parser.add_argument("--price-type", choices=("market", "limit"))
    parser.add_argument("--price", type=_parse_positive_decimal)
    parser.add_argument("--timeout-seconds", type=_parse_positive_int, default=60)
    parser.add_argument("--side", choices=("buy", "sell"))
    return parser


def parse_cli_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """解析并校验 M0/M1 模式所需参数。"""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.mode == "m1":
        if not args.symbol:
            parser.error("--mode m1 时必须提供 --symbol")
        if args.volume is None:
            parser.error("--mode m1 时必须提供 --volume")
        if not args.price_type:
            parser.error("--mode m1 时必须提供 --price-type")
        if args.price_type == "limit" and args.price is None:
            parser.error("--price-type limit 时必须提供 --price")
        if args.price_type == "market" and args.price is not None:
            parser.error("--price-type market 时不能提供 --price")
        if not args.side:
            parser.error("--mode m1 时必须提供 --side")

    return args


def main() -> int:
    """根据模式选择连通性检查或 M1 手工交易验证。"""
    args = parse_cli_args()
    from gmtrade_live.bootstrap import run_m0_connectivity_check, run_m1_manual_trade

    config_path = Path(args.config)
    if args.mode == "m1":
        return run_m1_manual_trade(
            config_path=config_path,
            symbol=args.symbol,
            volume=args.volume,
            price_type=args.price_type,
            price=args.price,
            timeout_seconds=args.timeout_seconds,
            side=args.side,
        )
    return run_m0_connectivity_check(config_path)


if __name__ == "__main__":
    raise SystemExit(main())
