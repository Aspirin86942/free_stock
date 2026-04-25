"""配置加载与校验逻辑。"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from gmtrade_live.errors import ServiceError


class ConfigurationError(ServiceError):
    """配置相关错误。"""

    pass


@dataclass(frozen=True, slots=True)
class AppConfig:
    """应用运行所需的只读配置快照（向后兼容，用于自动交易主链）。"""

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


@dataclass(frozen=True, slots=True)
class GmConfig:
    """掘金 API 共享配置。"""

    token: str
    endpoint: str
    timezone: str


@dataclass(frozen=True, slots=True)
class TradeConfig:
    """自动交易链路配置。"""

    enabled: bool
    account_id: str
    strategy_name: str
    poll_interval_seconds: int
    take_profit_ratio: Decimal
    stop_loss_ratio: Decimal
    sell_quantity_ratio: Decimal
    market_session_mode: str


@dataclass(frozen=True, slots=True)
class MarketAnalysisConfig:
    """盘后市场分析链路配置。"""

    enabled: bool
    universe: str
    history_years: int
    recent_trade_days: int
    report_time: str


@dataclass(frozen=True, slots=True)
class MySQLConfig:
    """MySQL 数据库配置。"""

    host: str
    port: int
    database: str
    user: str
    password: str


@dataclass(frozen=True, slots=True)
class FeishuConfig:
    """飞书通知配置。"""

    webhook: str


@dataclass(frozen=True, slots=True)
class SchedulerConfig:
    """调度器配置。"""

    enabled: bool
    retry_interval_minutes: int
    max_attempts: int


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """运行时完整配置（包含所有子配置块）。"""

    gm: GmConfig
    trade: TradeConfig
    market_analysis: MarketAnalysisConfig
    mysql: MySQLConfig
    feishu: FeishuConfig
    scheduler: SchedulerConfig
    log_dir: Path


_ENV_PATTERN = re.compile(r"^\$\{(?P<name>[A-Z0-9_]+)(?::-(?P<default>.*))?\}$")
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
    """解析 `${ENV_NAME}` 或 `${ENV_NAME:-default}` 形式的环境变量引用。"""
    if not isinstance(value, str):
        return value

    match = _ENV_PATTERN.match(value)
    if not match:
        return value

    env_name = match.group("name")
    default_value = match.group("default")
    env_value = os.getenv(env_name)

    if not env_value:
        if default_value is not None:
            return default_value
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
    """解析每轮自动卖出比例，并把范围限制收口在配置层。"""
    result = _parse_decimal(value, field_name)
    if result > Decimal("1"):
        _raise(
            "config.invalid_sell_quantity_ratio",
            f"字段 {field_name} 必须小于等于 1",
            context={"field": field_name, "value": str(value)},
        )
    return result


def _parse_bool(value: Any, field_name: str) -> bool:
    """把配置值解析成布尔值，避免字符串 'false' 被 Python 视为 True。"""
    if isinstance(value, bool):
        return value

    if isinstance(value, int):
        if value in (0, 1):
            return bool(value)
        _raise(
            "config.invalid_bool",
            f"字段 {field_name} 必须是布尔值",
            context={"field": field_name, "value": str(value)},
        )

    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off"}:
            return False

    _raise(
        "config.invalid_bool",
        f"字段 {field_name} 必须是布尔值",
        context={"field": field_name, "value": str(value)},
    )


def _resolve_env_recursive(value: Any, field_path: str) -> Any:
    """递归解析嵌套字典中的环境变量引用。"""
    if isinstance(value, dict):
        return {k: _resolve_env_recursive(v, f"{field_path}.{k}") for k, v in value.items()}
    return _resolve_env(value, field_path)


def _load_yaml_mapping(config_path: Path) -> dict[str, Any]:
    """读取 YAML 文件并确保根节点是字典。"""
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
    return raw


def _build_app_config_from_legacy_mapping(raw: dict[str, Any]) -> AppConfig:
    """从旧版顶层字段配置构建 AppConfig。"""

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


def _require_mapping(raw: dict[str, Any], section_name: str) -> dict[str, Any]:
    """读取嵌套配置块；缺少或类型错误时给出结构化配置错误。"""
    section = raw.get(section_name)
    if not isinstance(section, dict):
        _raise(
            "config.invalid_section",
            f"{section_name} 配置块必须是字典结构",
            context={"section": section_name},
        )
    return section


def _require_non_empty_value(
    raw: dict[str, Any],
    field_name: str,
    *,
    fallback: Any | None = None,
) -> Any:
    """读取必需值，兼容“主字段优先、共享字段兜底”的迁移期配置。"""
    value = raw.get(field_name)
    if value in (None, ""):
        value = fallback
    if value in (None, ""):
        _raise(
            "config.missing_field",
            f"缺少必填字段 {field_name}",
            context={"field": field_name},
        )
    return value


def _build_app_config_from_nested_mapping(raw: dict[str, Any]) -> AppConfig:
    """从新版嵌套配置派生旧入口仍需使用的 AppConfig。"""
    gm_raw = _resolve_env_recursive(_require_mapping(raw, "gm"), "gm")
    trade_raw = _resolve_env_recursive(_require_mapping(raw, "trade"), "trade")
    log_dir = _resolve_env(raw.get("log_dir", "logs"), "log_dir")

    # 迁移期允许 trade.token 覆盖 gm.token；绝大多数场景仍由 gm.token 统一承载掘金 Token。
    token = _require_non_empty_value(
        trade_raw,
        "token",
        fallback=gm_raw.get("token"),
    )

    return AppConfig(
        account_id=str(_require_non_empty_value(trade_raw, "account_id")),
        token=str(token),
        strategy_name=str(trade_raw.get("strategy_name", "gmtrade-live-auto-sell")),
        poll_interval_seconds=_parse_positive_int(
            trade_raw.get("poll_interval_seconds", 5),
            "trade.poll_interval_seconds",
        ),
        take_profit_ratio=_parse_decimal(
            trade_raw.get("take_profit_ratio", "0.015"),
            "trade.take_profit_ratio",
        ),
        stop_loss_ratio=_parse_decimal(
            trade_raw.get("stop_loss_ratio", "0.02"),
            "trade.stop_loss_ratio",
        ),
        sell_quantity_ratio=_parse_sell_quantity_ratio(
            trade_raw.get("sell_quantity_ratio", "0.02"),
            "trade.sell_quantity_ratio",
        ),
        market_session_mode=_parse_market_session_mode(
            trade_raw.get("market_session_mode", "a_share"),
            "trade.market_session_mode",
        ),
        log_dir=Path(str(log_dir)),
        timezone=str(gm_raw.get("timezone", "Asia/Shanghai")),
        gmtrade_endpoint=str(gm_raw.get("endpoint", "127.0.0.1:7001")),
    )


def load_config(config_path: Path) -> AppConfig:
    """读取 YAML 配置并转换为类型安全的应用配置（兼容旧版顶层与新版嵌套结构）。"""
    raw = _load_yaml_mapping(config_path)
    if isinstance(raw.get("trade"), dict) and isinstance(raw.get("gm"), dict):
        return _build_app_config_from_nested_mapping(raw)
    return _build_app_config_from_legacy_mapping(raw)


def load_runtime_config(config_path: Path) -> RuntimeConfig:
    """读取嵌套 YAML 配置并转换为运行时配置（用于 scheduler 和盘后分析）。"""
    raw = _load_yaml_mapping(config_path)

    # 递归解析环境变量
    resolved = _resolve_env_recursive(raw, "root")

    # 校验必需的顶层 section
    required_sections = ["gm", "trade", "market_analysis", "mysql", "feishu", "scheduler"]
    for section in required_sections:
        if section not in resolved:
            _raise(
                "config.missing_section",
                f"缺少必需配置块 {section}",
                context={"section": section},
            )

    # 解析 gm 配置
    gm_raw = resolved["gm"]
    if not isinstance(gm_raw, dict):
        _raise("config.invalid_section", "gm 配置块必须是字典结构")

    gm_config = GmConfig(
        token=str(gm_raw.get("token", "")),
        endpoint=str(gm_raw.get("endpoint", "127.0.0.1:7001")),
        timezone=str(gm_raw.get("timezone", "Asia/Shanghai")),
    )

    # 解析 trade 配置
    trade_raw = resolved["trade"]
    if not isinstance(trade_raw, dict):
        _raise("config.invalid_section", "trade 配置块必须是字典结构")

    trade_config = TradeConfig(
        enabled=_parse_bool(trade_raw.get("enabled", False), "trade.enabled"),
        account_id=str(trade_raw.get("account_id", "")),
        strategy_name=str(trade_raw.get("strategy_name", "gmtrade-live-auto-sell")),
        poll_interval_seconds=_parse_positive_int(
            trade_raw.get("poll_interval_seconds", 5), "trade.poll_interval_seconds"
        ),
        take_profit_ratio=_parse_decimal(
            trade_raw.get("take_profit_ratio", "0.015"), "trade.take_profit_ratio"
        ),
        stop_loss_ratio=_parse_decimal(
            trade_raw.get("stop_loss_ratio", "0.02"), "trade.stop_loss_ratio"
        ),
        sell_quantity_ratio=_parse_sell_quantity_ratio(
            trade_raw.get("sell_quantity_ratio", "0.02"), "trade.sell_quantity_ratio"
        ),
        market_session_mode=_parse_market_session_mode(
            trade_raw.get("market_session_mode", "a_share"), "trade.market_session_mode"
        ),
    )

    # 解析 market_analysis 配置
    ma_raw = resolved["market_analysis"]
    if not isinstance(ma_raw, dict):
        _raise("config.invalid_section", "market_analysis 配置块必须是字典结构")

    market_analysis_config = MarketAnalysisConfig(
        enabled=_parse_bool(ma_raw.get("enabled", True), "market_analysis.enabled"),
        universe=str(ma_raw.get("universe", "ashare_main_gem_star")),
        history_years=int(ma_raw.get("history_years", 3)),
        recent_trade_days=int(ma_raw.get("recent_trade_days", 10)),
        report_time=str(ma_raw.get("report_time", "19:15")),
    )

    # 解析 mysql 配置
    mysql_raw = resolved["mysql"]
    if not isinstance(mysql_raw, dict):
        _raise("config.invalid_section", "mysql 配置块必须是字典结构")

    mysql_config = MySQLConfig(
        host=str(mysql_raw.get("host", "127.0.0.1")),
        port=int(mysql_raw.get("port", 3306)),
        database=str(mysql_raw.get("database", "market_data")),
        user=str(mysql_raw.get("user", "")),
        password=str(mysql_raw.get("password", "")),
    )

    # 解析 feishu 配置
    feishu_raw = resolved["feishu"]
    if not isinstance(feishu_raw, dict):
        _raise("config.invalid_section", "feishu 配置块必须是字典结构")

    feishu_config = FeishuConfig(
        webhook=str(feishu_raw.get("webhook", "")),
    )

    # 解析 scheduler 配置
    scheduler_raw = resolved["scheduler"]
    if not isinstance(scheduler_raw, dict):
        _raise("config.invalid_section", "scheduler 配置块必须是字典结构")

    scheduler_config = SchedulerConfig(
        enabled=_parse_bool(scheduler_raw.get("enabled", True), "scheduler.enabled"),
        retry_interval_minutes=int(scheduler_raw.get("retry_interval_minutes", 10)),
        max_attempts=int(scheduler_raw.get("max_attempts", 3)),
    )

    # 解析 log_dir（顶层字段）
    log_dir = Path(str(resolved.get("log_dir", "logs")))

    return RuntimeConfig(
        gm=gm_config,
        trade=trade_config,
        market_analysis=market_analysis_config,
        mysql=mysql_config,
        feishu=feishu_config,
        scheduler=scheduler_config,
        log_dir=log_dir,
    )
