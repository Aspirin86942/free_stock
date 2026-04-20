"""统一运行入口，负责解析 CLI 子命令并分发执行。"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Sequence


def _ensure_local_src_on_path() -> None:
    """当环境里的 editable 安装失效时，允许直接从仓库根目录运行入口脚本。"""
    if importlib.util.find_spec("gmtrade_live") is not None:
        return

    repo_root = Path(__file__).resolve().parent
    src_path = repo_root / "src"
    if src_path.exists():
        sys.path.insert(0, str(src_path))


def _parse_positive_int(value: str) -> int:
    """把命令行整数参数解析为正数。"""
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("必须是整数") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("必须大于 0")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    """构建统一 CLI 参数。"""
    parser = argparse.ArgumentParser(
        description="GMTrade unified runtime entry"
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    trade_parser = subparsers.add_parser("trade", help="run auto-sell execution loop")
    trade_parser.add_argument("--config", required=True, help="Path to YAML config file")
    trade_group = trade_parser.add_mutually_exclusive_group()
    trade_group.add_argument("--once", action="store_true")
    trade_group.add_argument("--max-rounds", type=_parse_positive_int)
    trade_parser.add_argument(
        "--reconcile-timeout-seconds",
        type=_parse_positive_int,
        default=5,
    )

    scheduler_parser = subparsers.add_parser("scheduler", help="run market analysis scheduler")
    scheduler_parser.add_argument("--config", required=True, help="Path to YAML config file")
    scheduler_parser.add_argument(
        "--once",
        action="store_true",
        help="run one market-close task immediately",
    )

    return parser


def parse_cli_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """解析并校验 CLI 参数。"""
    parser = build_parser()
    return parser.parse_args(argv)


def _run_trade_command(args: argparse.Namespace) -> int:
    """执行自动卖出子命令。"""
    from gmtrade_live.app_runner import run_auto_sell

    config_path = Path(args.config)
    return run_auto_sell(
        config_path=config_path,
        once=args.once,
        max_rounds=args.max_rounds,
        reconcile_timeout_seconds=args.reconcile_timeout_seconds,
    )


def _run_scheduler_command(args: argparse.Namespace) -> int:
    """执行调度器子命令。"""
    from gmtrade_live.config import load_runtime_config
    from gmtrade_live.logging_setup import setup_logging
    from gmtrade_live.runtime_scheduler import RuntimeScheduler

    config_path = Path(args.config)
    config = load_runtime_config(config_path)
    setup_logging(
        strategy_name="market-analysis-scheduler",
        log_dir=Path(config.log_dir),
    )

    scheduler = RuntimeScheduler(config)
    if args.once:
        scheduler.run_once()
        return 0

    scheduler.start()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """执行统一入口。"""
    args = parse_cli_args(argv)
    _ensure_local_src_on_path()

    if args.command == "trade":
        return _run_trade_command(args)
    if args.command == "scheduler":
        return _run_scheduler_command(args)
    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
