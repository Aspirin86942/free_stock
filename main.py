"""自动卖出入口，负责解析 CLI 参数并分发执行。"""

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
    """构建自动卖出 CLI 参数。"""
    parser = argparse.ArgumentParser(
        description="GMTrade auto sell execution"
    )
    parser.add_argument("--config", required=True, help="Path to YAML config file")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--once", action="store_true")
    group.add_argument("--max-rounds", type=_parse_positive_int)
    parser.add_argument(
        "--reconcile-timeout-seconds",
        type=_parse_positive_int,
        default=5,
    )
    return parser


def parse_cli_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """解析并校验自动卖出 CLI 参数。"""
    parser = build_parser()
    return parser.parse_args(argv)


def main() -> int:
    """执行自动卖出入口。"""
    args = parse_cli_args()
    _ensure_local_src_on_path()
    from gmtrade_live.app_runner import run_auto_sell

    config_path = Path(args.config)
    return run_auto_sell(
        config_path=config_path,
        once=args.once,
        max_rounds=args.max_rounds,
        reconcile_timeout_seconds=args.reconcile_timeout_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
