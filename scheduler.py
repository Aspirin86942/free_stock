"""调度器 CLI 入口。

用法:
    python scheduler.py --config config/sim_account.yaml          # 启动常驻调度器
    python scheduler.py --config config/sim_account.yaml --once   # 手动触发一次盘后任务
"""

import argparse
import sys
from pathlib import Path

from gmtrade_live.config import load_runtime_config
from gmtrade_live.logging_setup import setup_logging
from gmtrade_live.runtime_scheduler import RuntimeScheduler


def main() -> int:
    """调度器主入口。"""
    parser = argparse.ArgumentParser(description="市场分析调度器")
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="配置文件路径",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="手动触发一次盘后任务（不启动常驻调度器）",
    )

    args = parser.parse_args()

    # 加载配置
    config = load_runtime_config(args.config)

    # 初始化日志
    setup_logging(
        log_dir=config.log_dir,
        strategy_name="market-analysis-scheduler",
        timezone=config.gm.timezone,
    )

    # 创建调度器
    scheduler = RuntimeScheduler(config)

    if args.once:
        # 手动触发一次
        scheduler.run_once()
        return 0
    else:
        # 启动常驻调度器
        scheduler.start()
        return 0


if __name__ == "__main__":
    sys.exit(main())
