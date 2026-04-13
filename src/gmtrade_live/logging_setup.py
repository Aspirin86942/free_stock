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
        fmt="%(asctime)s.%(msecs)03d %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_dir / "runtime.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    return logger


def setup_order_audit_logger(strategy_name: str, log_dir: Path) -> logging.Logger:
    """
    初始化独立的 order_audit 日志，仅记录 JSON Lines 原文，便于后端审计。
    """
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(f"{strategy_name}.order_audit")
    logger.setLevel(logging.INFO)
    # 先移除并关闭旧 handler，避免遗留打开的文件句柄。
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.propagate = False

    formatter = logging.Formatter(fmt="%(message)s")
    # 只保存 message 本体，保持 JSON Lines 原样，方便 downstream 解析。
    file_handler = logging.FileHandler(log_dir / "order_audit.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger
