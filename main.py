"""项目命令行入口，负责解析 M0/M1/M2 参数并分发执行。"""

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
    """构建基础 CLI 参数。"""
    parser = argparse.ArgumentParser(
        description="GMTrade connectivity, M1 manual trade, and M2 decision dry-run"
    )
    parser.add_argument("--config", required=True, help="Path to YAML config file")
    parser.add_argument("--mode", choices=("m0", "m1", "m2"), default="m0")
    parser.set_defaults(
        symbol=None,
        volume=None,
        price_type=None,
        price=None,
        timeout_seconds=60,
        side=None,
    )
    return parser


def build_parser_for_mode(mode: str) -> argparse.ArgumentParser:
    """按运行模式构建完整 CLI 参数。"""
    parser = build_parser()
    if mode == "m1":
        parser.add_argument("--symbol", required=True)
        parser.add_argument("--volume", type=_parse_positive_int, required=True)
        parser.add_argument("--price-type", choices=("market", "limit"), required=True)
        parser.add_argument("--price", type=_parse_positive_decimal)
        parser.add_argument("--timeout-seconds", type=_parse_positive_int, default=60)
        parser.add_argument("--side", choices=("buy", "sell"), required=True)
        return parser

    if mode == "m2":
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--once", action="store_true")
        group.add_argument("--max-rounds", type=_parse_positive_int)
    return parser


def _validate_mode_args(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> None:
    """补充 argparse 无法直接表达的参数组合约束。"""
    if args.mode != "m1":
        return
    if args.price_type == "limit" and args.price is None:
        parser.error("--price-type limit 时必须提供 --price")
    if args.price_type == "market" and args.price is not None:
        parser.error("--price-type market 时不能提供 --price")


def parse_cli_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """按模式解析并校验 CLI 参数。"""
    parser = build_parser()
    # 先只识别 mode，再按 mode 注册专属参数，避免无关模式误收参数。
    base_args, _ = parser.parse_known_args(argv)
    mode_parser = build_parser_for_mode(base_args.mode)
    args = mode_parser.parse_args(argv)
    _validate_mode_args(mode_parser, args)

    return args


def main() -> int:
    """根据模式选择连通性检查、M1 或 M2。"""
    args = parse_cli_args()
    from gmtrade_live.bootstrap import (
        run_m0_connectivity_check,
        run_m1_manual_trade,
        run_m2_dry_run,
    )

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
    if args.mode == "m2":
        return run_m2_dry_run(
            config_path=config_path,
            once=args.once,
            max_rounds=args.max_rounds,
        )
    return run_m0_connectivity_check(config_path)


if __name__ == "__main__":
    raise SystemExit(main())
