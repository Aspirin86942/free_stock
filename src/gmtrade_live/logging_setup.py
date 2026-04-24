"""日志初始化逻辑。"""

from __future__ import annotations

import logging
import sys
from pathlib import Path


def _reset_logger_handlers(logger: logging.Logger) -> None:
    """重置 logger 的 handler，避免重启或重复初始化后重复写日志。"""
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def _build_runtime_handlers(
    log_dir: Path,
    *,
    stream: object | None = None,
) -> tuple[logging.Handler, logging.Handler]:
    """创建运行日志所需的文件与控制台 handler。"""
    formatter = logging.Formatter(
        fmt="%(asctime)s.%(msecs)03d %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_dir / "runtime.log", encoding="utf-8")
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler(stream=stream)
    stream_handler.setFormatter(formatter)

    return file_handler, stream_handler


def _configure_runtime_logger(
    logger_name: str,
    log_dir: Path,
    *,
    propagate: bool,
    stream: object | None = None,
) -> logging.Logger:
    """按统一格式配置指定 logger。"""
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    _reset_logger_handlers(logger)
    logger.propagate = propagate

    for handler in _build_runtime_handlers(log_dir, stream=stream):
        logger.addHandler(handler)

    return logger


def setup_logging(strategy_name: str, log_dir: Path) -> logging.Logger:
    """为单策略运行实例初始化文件和控制台日志。"""
    log_dir.mkdir(parents=True, exist_ok=True)

    # 业务层既有直接注入的策略 logger，也有 gmtrade_live.* 模块 logger。
    # 两条链路都要落到同一份运行日志，否则调度器/飞书模块会出现“命令执行了但无日志”的假象。
    # gmtrade_live 包级 logger 使用真实 stderr，并保留向上传播，避免 pytest 捕获流关闭后遗留坏 handler，
    # 同时让 caplog 仍能观测到模块日志。
    _configure_runtime_logger(
        "gmtrade_live",
        log_dir,
        propagate=True,
        stream=sys.__stderr__,
    )
    return _configure_runtime_logger(strategy_name, log_dir, propagate=False)


def setup_order_audit_logger(strategy_name: str, log_dir: Path) -> logging.Logger:
    """
    初始化独立的 order_audit 日志，仅记录 JSON Lines 原文，便于后端审计。
    """
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(f"{strategy_name}.order_audit")
    logger.setLevel(logging.INFO)
    # 先移除并关闭旧 handler，避免遗留打开的文件句柄。
    _reset_logger_handlers(logger)
    logger.propagate = False

    formatter = logging.Formatter(fmt="%(message)s")
    # 只保存 message 本体，保持 JSON Lines 原样，方便 downstream 解析。
    file_handler = logging.FileHandler(log_dir / "order_audit.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger
