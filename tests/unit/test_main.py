from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import main


def test_build_parser_accepts_config_argument() -> None:
    parser = main.build_parser()
    args = parser.parse_args(["--config", "config/sim_account.yaml"])

    assert Path(args.config) == Path("config/sim_account.yaml")


def test_parse_cli_args_defaults_to_auto_sell() -> None:
    args = main.parse_cli_args(["--config", "config/sim_account.yaml"])

    assert args.config == "config/sim_account.yaml"
    assert args.once is False
    assert args.max_rounds is None
    assert args.reconcile_timeout_seconds == 5


def test_parse_cli_args_accepts_once_mode() -> None:
    args = main.parse_cli_args(
        [
            "--config",
            "config/sim_account.yaml",
            "--once",
        ]
    )

    assert args.once is True
    assert args.max_rounds is None


def test_parse_cli_args_accepts_max_rounds() -> None:
    args = main.parse_cli_args(
        [
            "--config",
            "config/sim_account.yaml",
            "--max-rounds",
            "3",
        ]
    )

    assert args.once is False
    assert args.max_rounds == 3


def test_parse_cli_args_rejects_once_and_max_rounds() -> None:
    with pytest.raises(SystemExit):
        main.parse_cli_args(
            [
                "--config",
                "config/sim_account.yaml",
                "--once",
                "--max-rounds",
                "3",
            ]
        )


def test_parse_cli_args_rejects_non_positive_max_rounds() -> None:
    with pytest.raises(SystemExit):
        main.parse_cli_args(
            [
                "--config",
                "config/sim_account.yaml",
                "--max-rounds",
                "0",
            ]
        )


def test_parse_cli_args_rejects_mode_argument(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main.parse_cli_args(
            [
                "--config",
                "config/sim_account.yaml",
                "--mode",
                "legacy",
            ]
        )

    captured = capsys.readouterr()
    assert "unrecognized arguments: --mode legacy" in captured.err


def test_parse_cli_args_accepts_reconcile_timeout_seconds() -> None:
    args = main.parse_cli_args(
        [
            "--config",
            "config/sim_account.yaml",
            "--reconcile-timeout-seconds",
            "7",
        ]
    )

    assert args.reconcile_timeout_seconds == 7


def test_main_dispatches_to_auto_sell(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _run_auto_sell(**kwargs: object) -> int:
        captured.update(kwargs)
        return 0

    runner = SimpleNamespace(
        run_auto_sell=_run_auto_sell,
    )

    monkeypatch.setitem(sys.modules, "gmtrade_live.app_runner", runner)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--config",
            "config/sim_account.yaml",
            "--once",
            "--reconcile-timeout-seconds",
            "7",
        ],
    )

    assert main.main() == 0
    assert captured["config_path"] == Path("config/sim_account.yaml")
    assert captured["once"] is True
    assert captured["max_rounds"] is None
    assert captured["reconcile_timeout_seconds"] == 7
