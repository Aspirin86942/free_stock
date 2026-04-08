from __future__ import annotations

import argparse
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GMTrade M0 connectivity check")
    parser.add_argument("--config", required=True, help="Path to YAML config file")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    from gmtrade_live.bootstrap import run_m0_connectivity_check

    return run_m0_connectivity_check(Path(args.config))


if __name__ == "__main__":
    raise SystemExit(main())
