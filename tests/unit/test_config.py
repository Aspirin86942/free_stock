from decimal import Decimal
from pathlib import Path

import pytest

from gmtrade_live.config import AppConfig, ConfigurationError, load_config


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
                "strategy_name: gmtrade-live-m0",
                "poll_interval_seconds: 5",
                "take_profit_ratio: '0.05'",
                "stop_loss_ratio: '0.03'",
                "trade_session_start: '09:30:00'",
                "trade_session_end: '15:00:00'",
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


def test_load_config_rejects_missing_required_field(tmp_path: Path) -> None:
    config_file = tmp_path / "broken.yaml"
    config_file.write_text("account_id: demo-account\n", encoding="utf-8")

    with pytest.raises(ConfigurationError) as exc_info:
        load_config(config_file)

    assert exc_info.value.code == "config.missing_field"
    assert exc_info.value.retryable is False
