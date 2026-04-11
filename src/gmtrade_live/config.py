"""配置加载与校验逻辑。"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import os
from pathlib import Path
import re
from typing import Any

import yaml

from gmtrade_live.errors import ServiceError


class ConfigurationError(ServiceError):
    """配置相关错误。"""

    pass


@dataclass(frozen=True, slots=True)
class AppConfig:
    """应用运行所需的只读配置快照。"""

    account_id: str
    token: str
    strategy_name: str
    poll_interval_seconds: int
    take_profit_ratio: Decimal
    stop_loss_ratio: Decimal
    sell_quantity_ratio: Decimal
    market_session_mode: str
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
    "sell_quantity_ratio",
    "market_session_mode",
    "log_dir",
)
_SUPPORTED_MARKET_SESSION_MODES = {"a_share", "futures_placeholder"}


def _raise(code: str, message: str, *, context: dict[str, str] | None = None) -> None:
    """统一抛出带上下文的配置异常。"""
    raise ConfigurationError(
        code=code,
        message=message,
        retryable=False,
        context=context or {},
    )


def _resolve_env(value: Any, field_name: str) -> Any:
    """解析 `${ENV_NAME}` 形式的环境变量引用。"""
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
    """把配置值解析成正 Decimal。"""
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
    """把配置值解析成正整数。"""
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


def _parse_market_session_mode(value: Any, field_name: str) -> str:
    """校验市场交易时段模式，避免不同市场共用一套错误时间窗口。"""
    if not isinstance(value, str) or not value.strip():
        _raise(
            "config.invalid_market_session_mode",
            f"字段 {field_name} 必须是非空字符串",
            context={"field": field_name, "value": str(value)},
        )

    result = value.strip()
    if result not in _SUPPORTED_MARKET_SESSION_MODES:
        _raise(
            "config.invalid_market_session_mode",
            f"字段 {field_name} 不支持 {result}",
            context={
                "field": field_name,
                "value": result,
                "supported": ",".join(sorted(_SUPPORTED_MARKET_SESSION_MODES)),
            },
        )
    return result


def _parse_sell_quantity_ratio(value: Any, field_name: str) -> Decimal:
    """解析 M3 每轮卖出比例，并把范围限制收口在配置层。"""
    result = _parse_decimal(value, field_name)
    if result > Decimal("1"):
        _raise(
            "config.invalid_sell_quantity_ratio",
            f"字段 {field_name} 必须小于等于 1",
            context={"field": field_name, "value": str(value)},
        )
    return result


def load_config(config_path: Path) -> AppConfig:
    """读取 YAML 配置并转换为类型安全的应用配置。"""
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

    # 先统一做环境变量替换，再进入类型校验，避免同一字段在多处重复解析。
    resolved = {key: _resolve_env(value, key) for key, value in raw.items()}
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
        sell_quantity_ratio=_parse_sell_quantity_ratio(
            resolved["sell_quantity_ratio"],
            "sell_quantity_ratio",
        ),
        market_session_mode=_parse_market_session_mode(
            resolved["market_session_mode"],
            "market_session_mode",
        ),
        log_dir=Path(str(resolved["log_dir"])),
        timezone=str(resolved.get("timezone", "Asia/Shanghai")),
        gmtrade_endpoint=str(resolved.get("gmtrade_endpoint", "127.0.0.1:7001")),
    )
