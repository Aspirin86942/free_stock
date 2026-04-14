from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import observe_decisions


def test_build_parser_accepts_config_argument() -> None:
    parser = observe_decisions.build_parser()
    args = parser.parse_args(["--config", "config/sim_account.yaml"])

    assert Path(args.config) == Path("config/sim_account.yaml")


def test_parse_cli_args_defaults_to_observer() -> None:
    args = observe_decisions.parse_cli_args(["--config", "config/sim_account.yaml"])

    assert args.config == "config/sim_account.yaml"
    assert args.once is False
    assert args.max_rounds is None


def test_parse_cli_args_accepts_once_mode() -> None:
    args = observe_decisions.parse_cli_args(
        [
            "--config",
            "config/sim_account.yaml",
            "--once",
        ]
    )

    assert args.once is True
    assert args.max_rounds is None


def test_parse_cli_args_accepts_max_rounds() -> None:
    args = observe_decisions.parse_cli_args(
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
        observe_decisions.parse_cli_args(
            [
                "--config",
                "config/sim_account.yaml",
                "--once",
                "--max-rounds",
                "3",
            ]
        )


def test_parse_cli_args_rejects_reconcile_timeout_seconds(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        observe_decisions.parse_cli_args(
            [
                "--config",
                "config/sim_account.yaml",
                "--reconcile-timeout-seconds",
                "5",
            ]
        )

    captured = capsys.readouterr()
    assert "unrecognized arguments: --reconcile-timeout-seconds 5" in captured.err


def test_main_dispatches_to_decision_observer(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _run_decision_observer(**kwargs: object) -> int:
        captured.update(kwargs)
        return 0

    runner = SimpleNamespace(
        run_decision_observer=_run_decision_observer,
    )

    monkeypatch.setitem(sys.modules, "gmtrade_live.app_runner", runner)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "observe_decisions.py",
            "--config",
            "config/sim_account.yaml",
            "--max-rounds",
            "2",
        ],
    )

    assert observe_decisions.main() == 0
    assert captured["config_path"] == Path("config/sim_account.yaml")
    assert captured["once"] is False
    assert captured["max_rounds"] == 2
