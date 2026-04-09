"""日志初始化逻辑。"""

from __future__ import annotations

import logging
from pathlib import Path


def setup_logging(strategy_name: str, log_dir: Path) -> logging.Logger:
    """为单策略运行实例初始化文件和控制台日志。"""
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(strategy_name)
    logger.setLevel(logging.INFO)
    # 重复初始化时先清掉旧 handler，避免测试或重启后日志重复输出。
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_dir / "runtime.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    return logger
