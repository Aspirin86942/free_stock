from pathlib import Path

from gmtrade_live.config import load_runtime_config


def test_load_runtime_config_parses_string_false_as_false(tmp_path: Path) -> None:
    config_file = tmp_path / "runtime.yaml"
    config_file.write_text(
        "\n".join(
            [
                "gm:",
                "  token: demo-token",
                "trade:",
                "  enabled: 'false'",
                "  account_id: demo-account",
                "  strategy_name: gmtrade-live-auto-sell",
                "  poll_interval_seconds: 5",
                "  take_profit_ratio: '0.015'",
                "  stop_loss_ratio: '0.02'",
                "  sell_quantity_ratio: '0.02'",
                "  market_session_mode: a_share",
                "market_analysis:",
                "  enabled: 'true'",
                "  universe: ashare_main_gem_star",
                "  history_years: 3",
                "  recent_trade_days: 10",
                "  report_time: '19:15'",
                "mysql:",
                "  host: 127.0.0.1",
                "  port: 3306",
                "  database: market_data",
                "  user: demo-user",
                "  password: demo-password",
                "feishu:",
                "  webhook: https://example.invalid/webhook",
                "scheduler:",
                "  enabled: 'false'",
                "  retry_interval_minutes: 10",
                "  max_attempts: 3",
                "log_dir: logs",
            ]
        ),
        encoding="utf-8",
    )

    config = load_runtime_config(config_file)

    assert config.trade.enabled is False
    assert config.market_analysis.enabled is True
    assert config.scheduler.enabled is False
