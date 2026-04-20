from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import main


def test_run_trade_command_calls_run_auto_sell(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _run_auto_sell(**kwargs: object) -> int:
        captured.update(kwargs)
        return 0

    monkeypatch.setitem(sys.modules, "gmtrade_live.app_runner", SimpleNamespace(run_auto_sell=_run_auto_sell))

    args = SimpleNamespace(
        config="config/sim_account.yaml",
        once=True,
        max_rounds=None,
        reconcile_timeout_seconds=7,
    )
    result = main._run_trade_command(args)

    assert result == 0
    assert captured["config_path"] == Path("config/sim_account.yaml")
    assert captured["once"] is True
    assert captured["max_rounds"] is None
    assert captured["reconcile_timeout_seconds"] == 7


def test_run_scheduler_command_calls_run_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    fake_config = SimpleNamespace(log_dir="logs")

    class _FakeScheduler:
        def __init__(self, config: object) -> None:
            assert config is fake_config

        def run_once(self) -> None:
            calls.append("once")

        def start(self) -> None:
            calls.append("start")

    monkeypatch.setitem(
        sys.modules,
        "gmtrade_live.config",
        SimpleNamespace(load_runtime_config=lambda _: fake_config),
    )
    monkeypatch.setitem(
        sys.modules,
        "gmtrade_live.logging_setup",
        SimpleNamespace(setup_logging=lambda strategy_name, log_dir: None),
    )
    monkeypatch.setitem(
        sys.modules,
        "gmtrade_live.runtime_scheduler",
        SimpleNamespace(RuntimeScheduler=_FakeScheduler),
    )

    args = SimpleNamespace(config="config/sim_account.yaml", once=True)
    result = main._run_scheduler_command(args)

    assert result == 0
    assert calls == ["once"]


def test_run_scheduler_command_calls_start(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    fake_config = SimpleNamespace(log_dir="logs")

    class _FakeScheduler:
        def __init__(self, config: object) -> None:
            assert config is fake_config

        def run_once(self) -> None:
            calls.append("once")

        def start(self) -> None:
            calls.append("start")

    monkeypatch.setitem(
        sys.modules,
        "gmtrade_live.config",
        SimpleNamespace(load_runtime_config=lambda _: fake_config),
    )
    monkeypatch.setitem(
        sys.modules,
        "gmtrade_live.logging_setup",
        SimpleNamespace(setup_logging=lambda strategy_name, log_dir: None),
    )
    monkeypatch.setitem(
        sys.modules,
        "gmtrade_live.runtime_scheduler",
        SimpleNamespace(RuntimeScheduler=_FakeScheduler),
    )

    args = SimpleNamespace(config="config/sim_account.yaml", once=False)
    result = main._run_scheduler_command(args)

    assert result == 0
    assert calls == ["start"]
