from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from decimal import Decimal, InvalidOperation
import os
from pathlib import Path
import re
from typing import Any

import yaml

from gmtrade_live.errors import ServiceError


class ConfigurationError(ServiceError):
    pass


@dataclass(frozen=True, slots=True)
class AppConfig:
    account_id: str
    token: str
    strategy_name: str
    poll_interval_seconds: int
    take_profit_ratio: Decimal
    stop_loss_ratio: Decimal
    trade_session_start: str
    trade_session_end: str
    log_dir: Path
    timezone: str
    gmtrade_endpoint: str


_ENV_PATTERN = re.compile(r"^\$\{(?P<name>[A-Z0-9_]+)\}$")
_REQUIRED_FIELDS = (
    "account_id",
    "token",
    "strategy_name",
    "poll_interval_seconds",
    "take_profit_ratio",
    "stop_loss_ratio",
    "trade_session_start",
    "trade_session_end",
    "log_dir",
)


def _raise(code: str, message: str, *, context: dict[str, str] | None = None) -> None:
    raise ConfigurationError(
        code=code,
        message=message,
        retryable=False,
        context=context or {},
    )


def _resolve_env(value: Any, field_name: str) -> Any:
    if not isinstance(value, str):
        return value

    match = _ENV_PATTERN.match(value)
    if not match:
        return value

    env_name = match.group("name")
    env_value = os.getenv(env_name)
    if not env_value:
        _raise(
            "config.missing_env",
            f"字段 {field_name} 引用的环境变量 {env_name} 未设置",
            context={"field": field_name, "env_name": env_name},
        )
    return env_value


def _parse_decimal(value: Any, field_name: str) -> Decimal:
    try:
        # 后续阈值会直接参与价格计算，这里统一转成 Decimal，避免把 float 精度误差带进交易逻辑。
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        _raise(
            "config.invalid_decimal",
            f"字段 {field_name} 必须是合法小数",
            context={"field": field_name, "value": str(value)},
        )

    if result <= Decimal("0"):
        _raise(
            "config.invalid_decimal",
            f"字段 {field_name} 必须大于 0",
            context={"field": field_name, "value": str(value)},
        )
    return result


def _parse_positive_int(value: Any, field_name: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        _raise(
            "config.invalid_int",
            f"字段 {field_name} 必须是整数",
            context={"field": field_name, "value": str(value)},
        )

    if result <= 0:
        _raise(
            "config.invalid_int",
            f"字段 {field_name} 必须大于 0",
            context={"field": field_name, "value": str(value)},
        )
    return result


def _parse_trade_window(start_text: Any, end_text: Any) -> tuple[str, str]:
    try:
        start_value = time.fromisoformat(str(start_text))
        end_value = time.fromisoformat(str(end_text))
    except ValueError:
        _raise("config.invalid_trade_window", "交易时间必须是 HH:MM:SS 格式")

    if start_value >= end_value:
        _raise("config.invalid_trade_window", "交易开始时间必须早于结束时间")
    return str(start_text), str(end_text)


def load_config(config_path: Path) -> AppConfig:
    if not config_path.exists():
        _raise("config.not_found", "配置文件不存在", context={"path": str(config_path)})

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        _raise(
            "config.invalid_yaml",
            "配置文件不是合法 YAML",
            context={"path": str(config_path), "reason": str(exc)},
        )

    if not isinstance(raw, dict):
        _raise("config.invalid_root", "配置文件根节点必须是字典结构")

    for field_name in _REQUIRED_FIELDS:
        if field_name not in raw:
            _raise(
                "config.missing_field",
                f"缺少必填字段 {field_name}",
                context={"field": field_name},
            )

    resolved = {key: _resolve_env(value, key) for key, value in raw.items()}
    trade_session_start, trade_session_end = _parse_trade_window(
        resolved["trade_session_start"],
        resolved["trade_session_end"],
    )

    return AppConfig(
        account_id=str(resolved["account_id"]),
        token=str(resolved["token"]),
        strategy_name=str(resolved["strategy_name"]),
        poll_interval_seconds=_parse_positive_int(
            resolved["poll_interval_seconds"],
            "poll_interval_seconds",
        ),
        take_profit_ratio=_parse_decimal(
            resolved["take_profit_ratio"],
            "take_profit_ratio",
        ),
        stop_loss_ratio=_parse_decimal(
            resolved["stop_loss_ratio"],
            "stop_loss_ratio",
        ),
        trade_session_start=trade_session_start,
        trade_session_end=trade_session_end,
        log_dir=Path(str(resolved["log_dir"])),
        timezone=str(resolved.get("timezone", "Asia/Shanghai")),
        gmtrade_endpoint=str(resolved.get("gmtrade_endpoint", "api.myquant.cn:9000")),
    )
