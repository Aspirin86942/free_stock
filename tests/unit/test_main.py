from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

import main


def test_build_parser_accepts_config_argument() -> None:
    parser = main.build_parser()
    args = parser.parse_args(["--config", "config/sim_account.yaml"])

    assert Path(args.config) == Path("config/sim_account.yaml")


def test_parse_cli_args_defaults_to_m0() -> None:
    args = main.parse_cli_args(["--config", "config/sim_account.yaml"])

    assert args.mode == "m0"
    assert args.symbol is None
    assert not hasattr(args, "once")
    assert not hasattr(args, "max_rounds")


def test_parse_cli_args_accepts_m1_market_order() -> None:
    args = main.parse_cli_args(
        [
            "--config",
            "config/sim_account.yaml",
            "--mode",
            "m1",
            "--symbol",
            "SHSE.600036",
            "--volume",
            "100",
            "--price-type",
            "market",
            "--timeout-seconds",
            "90",
            "--side",
            "sell",
        ]
    )

    assert args.mode == "m1"
    assert args.symbol == "SHSE.600036"
    assert args.volume == 100
    assert args.price_type == "market"
    assert args.timeout_seconds == 90


def test_parse_cli_args_accepts_m1_buy_market_order() -> None:
    args = main.parse_cli_args(
        [
            "--config",
            "config/sim_account.yaml",
            "--mode",
            "m1",
            "--symbol",
            "SHSE.600036",
            "--volume",
            "100",
            "--price-type",
            "market",
            "--timeout-seconds",
            "90",
            "--side",
            "buy",
        ]
    )

    assert args.mode == "m1"
    assert args.side == "buy"


def test_parse_cli_args_requires_side_for_m1() -> None:
    with pytest.raises(SystemExit):
        main.parse_cli_args(
            [
                "--config",
                "config/sim_account.yaml",
                "--mode",
                "m1",
                "--symbol",
                "SHSE.600036",
                "--volume",
                "100",
                "--price-type",
                "market",
                "--timeout-seconds",
                "90",
            ]
        )


def test_parse_cli_args_requires_price_for_limit_order() -> None:
    with pytest.raises(SystemExit):
        main.parse_cli_args(
        [
            "--config",
            "config/sim_account.yaml",
            "--mode",
            "m1",
            "--symbol",
            "SHSE.600036",
            "--volume",
            "100",
            "--price-type",
            "limit",
            "--side",
            "sell",
        ]
        )


def test_parse_cli_args_rejects_non_positive_volume() -> None:
    with pytest.raises(SystemExit):
        main.parse_cli_args(
        [
            "--config",
            "config/sim_account.yaml",
            "--mode",
            "m1",
            "--symbol",
            "SHSE.600036",
            "--volume",
            "0",
            "--price-type",
            "market",
            "--side",
            "sell",
        ]
        )


def test_main_dispatches_to_m0(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _run_m0_connectivity_check(config_path: Path) -> int:
        captured["config"] = config_path
        return 0

    bootstrap = SimpleNamespace(
        run_m0_connectivity_check=_run_m0_connectivity_check,
        run_m1_manual_trade=lambda **kwargs: 1,
        run_m2_dry_run=lambda **kwargs: 1,
    )

    monkeypatch.setitem(sys.modules, "gmtrade_live.bootstrap", bootstrap)
    monkeypatch.setattr(
        sys,
        "argv",
        ["main.py", "--config", "config/sim_account.yaml"],
    )

    assert main.main() == 0
    assert captured["config"] == Path("config/sim_account.yaml")


def test_main_dispatches_to_m1(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _run_m1_manual_trade(**kwargs: object) -> int:
        captured.update(kwargs)
        return 0

    bootstrap = SimpleNamespace(
        run_m0_connectivity_check=lambda config_path: 1,
        run_m1_manual_trade=_run_m1_manual_trade,
        run_m2_dry_run=lambda **kwargs: 1,
    )

    monkeypatch.setitem(sys.modules, "gmtrade_live.bootstrap", bootstrap)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--config",
            "config/sim_account.yaml",
            "--mode",
            "m1",
            "--symbol",
            "SHSE.600036",
            "--volume",
            "100",
            "--price-type",
            "limit",
            "--price",
            "10.50",
            "--timeout-seconds",
            "120",
            "--side",
            "sell",
        ],
    )

    assert main.main() == 0
    assert captured["config_path"] == Path("config/sim_account.yaml")
    assert captured["symbol"] == "SHSE.600036"
    assert captured["volume"] == 100
    assert captured["price_type"] == "limit"
    assert captured["price"] == Decimal("10.50")
    assert captured["timeout_seconds"] == 120
    assert captured["side"] == "sell"


def test_parse_cli_args_accepts_m2_once_mode() -> None:
    args = main.parse_cli_args(
        [
            "--config",
            "config/sim_account.yaml",
            "--mode",
            "m2",
            "--once",
        ]
    )

    assert args.mode == "m2"
    assert args.once is True
    assert args.max_rounds is None


def test_parse_cli_args_rejects_once_outside_m2() -> None:
    with pytest.raises(SystemExit):
        main.parse_cli_args(
            [
                "--config",
                "config/sim_account.yaml",
                "--once",
            ]
        )


def test_parse_cli_args_reports_once_as_unrecognized_outside_m2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        main.parse_cli_args(
            [
                "--config",
                "config/sim_account.yaml",
                "--once",
            ]
        )

    captured = capsys.readouterr()
    assert "unrecognized arguments: --once" in captured.err


def test_main_dispatches_to_m2(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _run_m2_dry_run(**kwargs: object) -> int:
        captured.update(kwargs)
        return 0

    bootstrap = SimpleNamespace(
        run_m0_connectivity_check=lambda config_path: 1,
        run_m1_manual_trade=lambda **kwargs: 1,
        run_m2_dry_run=_run_m2_dry_run,
    )

    monkeypatch.setitem(sys.modules, "gmtrade_live.bootstrap", bootstrap)
    monkeypatch.setattr(
        sys,
        "argv",
        ["main.py", "--config", "config/sim_account.yaml", "--mode", "m2", "--max-rounds", "3"],
    )

    assert main.main() == 0
    assert captured["config_path"] == Path("config/sim_account.yaml")
    assert captured["once"] is False
    assert captured["max_rounds"] == 3
