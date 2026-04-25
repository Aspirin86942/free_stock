from decimal import Decimal
from pathlib import Path

import pytest

from gmtrade_live.config import (
    AppConfig,
    ConfigurationError,
    RuntimeConfig,
    load_config,
    load_runtime_config,
)


def test_load_config_reads_and_resolves_environment_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GM_ACCOUNT_ID", "demo-account")
    monkeypatch.setenv("GM_TOKEN", "demo-token")

    config_file = tmp_path / "sim_account.yaml"
    config_file.write_text(
        "\n".join(
            [
                "account_id: ${GM_ACCOUNT_ID}",
                "token: ${GM_TOKEN}",
                "strategy_name: gmtrade-live-auto-sell",
                "poll_interval_seconds: 5",
                "take_profit_ratio: '0.05'",
                "stop_loss_ratio: '0.03'",
                "sell_quantity_ratio: '1.0'",
                "market_session_mode: a_share",
                "log_dir: logs",
                "timezone: Asia/Shanghai",
                "gmtrade_endpoint: api.myquant.cn:9000",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(config_file)

    assert isinstance(config, AppConfig)
    assert config.account_id == "demo-account"
    assert config.token == "demo-token"
    assert config.take_profit_ratio == Decimal("0.05")
    assert config.stop_loss_ratio == Decimal("0.03")
    assert config.sell_quantity_ratio == Decimal("1.0")
    assert config.market_session_mode == "a_share"


def test_load_config_derives_app_config_from_nested_runtime_sections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GM_ACCOUNT_ID", "nested-account")
    monkeypatch.setenv("GM_TOKEN", "gm-token")
    monkeypatch.setenv("TRADE_TOKEN", "trade-token")
    monkeypatch.setenv("MYSQL_USER", "demo-user")
    monkeypatch.setenv("MYSQL_PASSWORD", "demo-password")
    monkeypatch.setenv("FEISHU_WEBHOOK", "https://example.invalid/webhook")

    config_file = tmp_path / "runtime.yaml"
    config_file.write_text(
        "\n".join(
            [
                "gm:",
                "  token: ${GM_TOKEN}",
                "  endpoint: 127.0.0.1:7001",
                "  timezone: Asia/Shanghai",
                "trade:",
                "  enabled: false",
                "  account_id: ${GM_ACCOUNT_ID}",
                "  token: ${TRADE_TOKEN}",
                "  strategy_name: gmtrade-live-auto-sell",
                "  poll_interval_seconds: 5",
                "  take_profit_ratio: '0.015'",
                "  stop_loss_ratio: '0.02'",
                "  sell_quantity_ratio: '0.02'",
                "  market_session_mode: a_share",
                "market_analysis:",
                "  enabled: true",
                "  universe: ashare_main_gem_star",
                "  history_years: 3",
                "  recent_trade_days: 10",
                "  report_time: '19:15'",
                "mysql:",
                "  host: 127.0.0.1",
                "  port: 3306",
                "  database: market_data",
                "  user: ${MYSQL_USER}",
                "  password: ${MYSQL_PASSWORD}",
                "feishu:",
                "  webhook: ${FEISHU_WEBHOOK}",
                "scheduler:",
                "  enabled: true",
                "  retry_interval_minutes: 10",
                "  max_attempts: 3",
                "log_dir: logs",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(config_file)

    assert isinstance(config, AppConfig)
    assert config.account_id == "nested-account"
    assert config.token == "trade-token"
    assert config.strategy_name == "gmtrade-live-auto-sell"
    assert config.take_profit_ratio == Decimal("0.015")
    assert config.gmtrade_endpoint == "127.0.0.1:7001"
    assert config.timezone == "Asia/Shanghai"


def test_load_config_rejects_missing_required_field(tmp_path: Path) -> None:
    config_file = tmp_path / "broken.yaml"
    config_file.write_text("account_id: demo-account\n", encoding="utf-8")

    with pytest.raises(ConfigurationError) as exc_info:
        load_config(config_file)

    assert exc_info.value.code == "config.missing_field"
    assert exc_info.value.retryable is False


def test_load_config_defaults_gmtrade_endpoint_to_local_terminal(tmp_path: Path) -> None:
    config_file = tmp_path / "sim_account.yaml"
    config_file.write_text(
        "\n".join(
            [
                "account_id: demo-account",
                "token: demo-token",
                "strategy_name: gmtrade-live-auto-sell",
                "poll_interval_seconds: 5",
                "take_profit_ratio: '0.05'",
                "stop_loss_ratio: '0.03'",
                "sell_quantity_ratio: '1.0'",
                "market_session_mode: a_share",
                "log_dir: logs",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(config_file)

    assert config.gmtrade_endpoint == "127.0.0.1:7001"


def test_load_config_accepts_futures_placeholder_mode(tmp_path: Path) -> None:
    config_file = tmp_path / "sim_account.yaml"
    config_file.write_text(
        "\n".join(
            [
                "account_id: demo-account",
                "token: demo-token",
                "strategy_name: gmtrade-live-auto-sell",
                "poll_interval_seconds: 5",
                "take_profit_ratio: '0.05'",
                "stop_loss_ratio: '0.03'",
                "sell_quantity_ratio: '1.0'",
                "market_session_mode: futures_placeholder",
                "log_dir: logs",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(config_file)

    assert config.market_session_mode == "futures_placeholder"


def test_load_config_reads_sell_quantity_ratio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GM_ACCOUNT_ID", "demo-account")
    monkeypatch.setenv("GM_TOKEN", "demo-token")

    config_file = tmp_path / "sim_account.yaml"
    config_file.write_text(
        "\n".join(
            [
                "account_id: ${GM_ACCOUNT_ID}",
                "token: ${GM_TOKEN}",
                "strategy_name: gmtrade-live-auto-sell",
                "poll_interval_seconds: 5",
                "take_profit_ratio: '0.05'",
                "stop_loss_ratio: '0.03'",
                "sell_quantity_ratio: '1.0'",
                "market_session_mode: a_share",
                "log_dir: logs",
                "timezone: Asia/Shanghai",
                "gmtrade_endpoint: 127.0.0.1:7001",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(config_file)

    assert config.sell_quantity_ratio == Decimal("1.0")


def test_load_config_rejects_missing_sell_quantity_ratio(tmp_path: Path) -> None:
    config_file = tmp_path / "broken.yaml"
    config_file.write_text(
        "\n".join(
            [
                "account_id: demo-account",
                "token: demo-token",
                "strategy_name: gmtrade-live-auto-sell",
                "poll_interval_seconds: 5",
                "take_profit_ratio: '0.05'",
                "stop_loss_ratio: '0.03'",
                "market_session_mode: a_share",
                "log_dir: logs",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError) as exc_info:
        load_config(config_file)

    assert exc_info.value.code == "config.missing_field"


def test_load_config_rejects_sell_quantity_ratio_above_one(tmp_path: Path) -> None:
    config_file = tmp_path / "broken.yaml"
    config_file.write_text(
        "\n".join(
            [
                "account_id: demo-account",
                "token: demo-token",
                "strategy_name: gmtrade-live-auto-sell",
                "poll_interval_seconds: 5",
                "take_profit_ratio: '0.05'",
                "stop_loss_ratio: '0.03'",
                "sell_quantity_ratio: '1.2'",
                "market_session_mode: a_share",
                "log_dir: logs",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError) as exc_info:
        load_config(config_file)

    assert exc_info.value.code == "config.invalid_sell_quantity_ratio"


def test_load_runtime_config_reads_nested_sections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GM_TOKEN", "demo-token")
    monkeypatch.setenv("GM_ACCOUNT_ID", "demo-account")
    monkeypatch.setenv("MYSQL_USER", "demo-user")
    monkeypatch.setenv("MYSQL_PASSWORD", "demo-password")
    monkeypatch.setenv("FEISHU_WEBHOOK", "https://example.invalid/webhook")

    config_file = tmp_path / "runtime.yaml"
    config_file.write_text(
        "\n".join(
            [
                "gm:",
                "  token: ${GM_TOKEN}",
                "  endpoint: 127.0.0.1:7001",
                "  timezone: Asia/Shanghai",
                "trade:",
                "  enabled: false",
                "  account_id: ${GM_ACCOUNT_ID}",
                "  strategy_name: gmtrade-live-auto-sell",
                "  poll_interval_seconds: 5",
                "  take_profit_ratio: '0.015'",
                "  stop_loss_ratio: '0.02'",
                "  sell_quantity_ratio: '0.02'",
                "  market_session_mode: a_share",
                "market_analysis:",
                "  enabled: true",
                "  universe: ashare_main_gem_star",
                "  history_years: 3",
                "  recent_trade_days: 10",
                "  report_time: '19:15'",
                "mysql:",
                "  host: 127.0.0.1",
                "  port: 3306",
                "  database: market_data",
                "  user: ${MYSQL_USER}",
                "  password: ${MYSQL_PASSWORD}",
                "feishu:",
                "  webhook: ${FEISHU_WEBHOOK}",
                "scheduler:",
                "  enabled: true",
                "  retry_interval_minutes: 10",
                "  max_attempts: 3",
                "log_dir: logs",
            ]
        ),
        encoding="utf-8",
    )

    config = load_runtime_config(config_file)

    assert isinstance(config, RuntimeConfig)
    assert config.gm.token == "demo-token"
    assert config.gm.endpoint == "127.0.0.1:7001"
    assert config.trade.enabled is False
    assert config.trade.account_id == "demo-account"
    assert config.trade.take_profit_ratio == Decimal("0.015")
    assert config.market_analysis.enabled is True
    assert config.market_analysis.report_time == "19:15"
    assert config.mysql.user == "demo-user"
    assert config.feishu.webhook == "https://example.invalid/webhook"
    assert config.scheduler.max_attempts == 3


def test_load_runtime_config_rejects_missing_section(tmp_path: Path) -> None:
    config_file = tmp_path / "broken.yaml"
    config_file.write_text(
        "\n".join(
            [
                "gm:",
                "  token: demo-token",
                "trade:",
                "  enabled: false",
                "log_dir: logs",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError) as exc_info:
        load_runtime_config(config_file)

    assert exc_info.value.code == "config.missing_section"
