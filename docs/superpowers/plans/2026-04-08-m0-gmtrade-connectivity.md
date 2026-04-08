# GMTrade M0 环境与账户连通 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `M0` baseline that can start the program, load validated config, connect to 东方财富掘金官方接口, read cash and positions, query quotes for current holdings, and leave a smoke-verifiable report.

**Architecture:** This plan creates a small Python 3.10 package with a thin CLI entry, explicit config and logging infrastructure, typed snapshot models, and two official adapters: `gmtrade` for账户/持仓查询 and `gm.api.current` for行情快照。M0 stops at connectivity and data-read validation; it does not implement decision logic, order submission, or callbacks yet.

**Tech Stack:** Python 3.10 x64, `gmtrade==3.0.6`, `gm==3.0.183`, `PyYAML`, `pytest`, stdlib `logging`, `decimal`, `zoneinfo`

---

## Planned File Structure

- Create: `.gitignore` - ignore local secret config, logs, caches, and test artifacts.
- Create: `pyproject.toml` - pin Python runtime and package dependencies.
- Create: `main.py` - CLI entrypoint for the M0 smoke run.
- Create: `config/sim_account.example.yaml` - checked-in example config using environment variables.
- Create: `src/gmtrade_live/__init__.py` - package marker.
- Create: `src/gmtrade_live/errors.py` - unified error model.
- Create: `src/gmtrade_live/config.py` - YAML config loading and validation.
- Create: `src/gmtrade_live/logging_setup.py` - runtime logger bootstrap with structured logging.
- Create: `src/gmtrade_live/session.py` - trade-session state calculation.
- Create: `src/gmtrade_live/models.py` - cash / position / quote / report models.
- Create: `src/gmtrade_live/precision.py` - data precision normalization functions.
- Create: `src/gmtrade_live/state.py` - position state manager (memory version).
- Create: `src/gmtrade_live/gateways/__init__.py` - gateway package marker.
- Create: `src/gmtrade_live/gateways/protocols.py` - trade and market gateway interfaces.
- Create: `src/gmtrade_live/gateways/gmtrade_trade_gateway.py` - official `gmtrade` adapter with precision normalization.
- Create: `src/gmtrade_live/gateways/gm_market_gateway.py` - official `gm.api.current` adapter with precision normalization.
- Create: `src/gmtrade_live/services/__init__.py` - services package marker.
- Create: `src/gmtrade_live/services/m0_connectivity.py` - M0 application service.
- Create: `src/gmtrade_live/bootstrap.py` - real wiring for config, logging, adapters, state manager, and service.
- Create: `tests/unit/test_main.py` - parser contract.
- Create: `tests/unit/test_config.py` - config validation tests.
- Create: `tests/unit/test_runtime.py` - logger and session tests.
- Create: `tests/unit/test_precision.py` - precision normalization tests.
- Create: `tests/unit/test_state.py` - state manager tests.
- Create: `tests/unit/test_official_gateways.py` - adapter mapping tests with fake SDK modules.
- Create: `tests/integration/test_m0_connectivity_service.py` - fake-driven M0 service integration test.

## Scope Guard

This plan covers only `M0 环境与账户连通`. It must deliver:

- program startup
- config validation
- local log file creation
- trade session state calculation
- official GM account connectivity
- account cash read
- position read
- quote read for current sellable holdings
- one smoke command that leaves console and file evidence

This plan does **not** deliver:

- stop-profit / stop-loss logic
- order submission
- order callbacks
- duplicate-order guard
- execution state machine

### Task 1: Bootstrap The Project Skeleton

**Files:**
- Create: `.gitignore`
- Create: `pyproject.toml`
- Create: `src/gmtrade_live/__init__.py`
- Create: `main.py`
- Test: `tests/unit/test_main.py`

- [ ] **Step 1: Write the failing parser test**

```python
from pathlib import Path

from main import build_parser


def test_build_parser_accepts_config_argument() -> None:
    parser = build_parser()
    args = parser.parse_args(["--config", "config/sim_account.yaml"])

    assert Path(args.config) == Path("config/sim_account.yaml")
```

- [ ] **Step 2: Run the parser test and verify it fails**

Run:

```powershell
conda run -n test pytest tests/unit/test_main.py -v
```

Expected: FAIL with `ModuleNotFoundError` or `ImportError`, because `main.py` and the package do not exist yet.

- [ ] **Step 3: Create the bootstrap files**

`.gitignore`

```gitignore
config/sim_account.yaml
logs/
.pytest_cache/
__pycache__/
*.pyc
```

`pyproject.toml`

```toml
[build-system]
requires = ["setuptools>=69", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "gmtrade-live"
version = "0.1.0"
description = "东方财富掘金第一期最小实盘闭环"
readme = "docs/Proposal/量化交易系统规划书.md"
requires-python = ">=3.10,<3.11"
dependencies = [
  "PyYAML>=6.0.2,<7.0.0",
  "gm==3.0.183",
  "gmtrade==3.0.6",
]

[tool.setuptools]
package-dir = {"" = "src"}

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src", "."]
testpaths = ["tests"]
addopts = "-ra"
```

`src/gmtrade_live/__init__.py`

```python
__all__ = ["__version__"]

__version__ = "0.1.0"
```

`main.py`

```python
from __future__ import annotations

import argparse
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GMTrade M0 connectivity check")
    parser.add_argument("--config", required=True, help="Path to YAML config file")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    from gmtrade_live.bootstrap import run_m0_connectivity_check

    return run_m0_connectivity_check(Path(args.config))


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the parser test again and verify it passes**

Run:

```powershell
conda run -n test pytest tests/unit/test_main.py -v
```

Expected: PASS. The parser test does not execute `main()`, so deferred imports inside `main()` are acceptable at this stage.

- [ ] **Step 5: Commit the bootstrap**

```powershell
git add .gitignore pyproject.toml main.py src/gmtrade_live/__init__.py tests/unit/test_main.py
git commit -m "build: bootstrap gmtrade live m0 project"
```

### Task 2: Add Error Model, Config Loading, Logging, Session Control, And Data Precision

**Files:**
- Create: `src/gmtrade_live/errors.py`
- Create: `src/gmtrade_live/config.py`
- Create: `src/gmtrade_live/logging_setup.py`
- Create: `src/gmtrade_live/session.py`
- Create: `src/gmtrade_live/precision.py`
- Create: `config/sim_account.example.yaml`
- Test: `tests/unit/test_config.py`
- Test: `tests/unit/test_runtime.py`
- Test: `tests/unit/test_precision.py`

- [ ] **Step 1: Write the failing config and runtime tests**

`tests/unit/test_config.py`

```python
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
```

`tests/unit/test_runtime.py`

```python
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from gmtrade_live.logging_setup import setup_logging
from gmtrade_live.session import TradingSessionState, resolve_trading_session


def test_setup_logging_creates_runtime_log_file(tmp_path: Path) -> None:
    logger = setup_logging("gmtrade-live-m0", tmp_path)
    logger.info("hello m0")

    assert (tmp_path / "runtime.log").exists()


def test_resolve_trading_session_returns_closed_day_on_saturday() -> None:
    saturday = datetime(2026, 4, 11, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    state = resolve_trading_session(
        saturday,
        start_text="09:30:00",
        end_text="15:00:00",
        timezone_name="Asia/Shanghai",
    )

    assert state is TradingSessionState.CLOSED_DAY
```

- [ ] **Step 2: Run the config and runtime tests and verify they fail**

Run:

```powershell
conda run -n test pytest tests/unit/test_config.py tests/unit/test_runtime.py -v
```

Expected: FAIL with `ModuleNotFoundError` for the new modules.

- [ ] **Step 3: Implement the error model, config loader, logger, and session resolver**

`src/gmtrade_live/errors.py`

```python
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ServiceError(Exception):
    code: str
    message: str
    retryable: bool
    context: dict[str, str] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"
```

`src/gmtrade_live/config.py`

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
import os
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


_ENV_PATTERN = re.compile(r"^\\$\\{(?P<name>[A-Z0-9_]+)\\}$")
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
        # 交易阈值后续会参与价格计算，这里先统一用 Decimal 收口精度。
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


def load_config(config_path: Path) -> AppConfig:
    if not config_path.exists():
        _raise("config.not_found", "配置文件不存在", context={"path": str(config_path)})

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
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

    start_value = time.fromisoformat(str(resolved["trade_session_start"]))
    end_value = time.fromisoformat(str(resolved["trade_session_end"]))
    if start_value >= end_value:
        _raise("config.invalid_trade_window", "交易开始时间必须早于结束时间")

    poll_interval = int(resolved["poll_interval_seconds"])
    if poll_interval <= 0:
        _raise("config.invalid_int", "poll_interval_seconds 必须大于 0")

    return AppConfig(
        account_id=str(resolved["account_id"]),
        token=str(resolved["token"]),
        strategy_name=str(resolved["strategy_name"]),
        poll_interval_seconds=poll_interval,
        take_profit_ratio=_parse_decimal(resolved["take_profit_ratio"], "take_profit_ratio"),
        stop_loss_ratio=_parse_decimal(resolved["stop_loss_ratio"], "stop_loss_ratio"),
        trade_session_start=str(resolved["trade_session_start"]),
        trade_session_end=str(resolved["trade_session_end"]),
        log_dir=Path(str(resolved["log_dir"])),
        timezone=str(resolved.get("timezone", "Asia/Shanghai")),
        gmtrade_endpoint=str(resolved.get("gmtrade_endpoint", "api.myquant.cn:9000")),
    )
```

`src/gmtrade_live/logging_setup.py`

```python
from __future__ import annotations

import logging
from pathlib import Path


def setup_logging(strategy_name: str, log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(strategy_name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_dir / "runtime.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    return logger
```

`src/gmtrade_live/session.py`

```python
from __future__ import annotations

from datetime import datetime, time
from enum import Enum
from zoneinfo import ZoneInfo


class TradingSessionState(str, Enum):
    PRE_OPEN = "pre_open"
    TRADING = "trading"
    POST_CLOSE = "post_close"
    CLOSED_DAY = "closed_day"


def resolve_trading_session(
    now: datetime,
    *,
    start_text: str,
    end_text: str,
    timezone_name: str,
) -> TradingSessionState:
    local_now = now.astimezone(ZoneInfo(timezone_name))
    start_time = time.fromisoformat(start_text)
    end_time = time.fromisoformat(end_text)
    current_time = local_now.timetz().replace(tzinfo=None)

    # 第一阶段先按周末和固定时间窗口判断，后续再替换成交易日历。
    if local_now.weekday() >= 5:
        return TradingSessionState.CLOSED_DAY
    if current_time < start_time:
        return TradingSessionState.PRE_OPEN
    if current_time > end_time:
        return TradingSessionState.POST_CLOSE
    return TradingSessionState.TRADING
```

`config/sim_account.example.yaml`

```yaml
account_id: ${GM_ACCOUNT_ID}
token: ${GM_TOKEN}
strategy_name: gmtrade-live-m0
poll_interval_seconds: 5
take_profit_ratio: "0.05"
stop_loss_ratio: "0.03"
trade_session_start: "09:30:00"
trade_session_end: "15:00:00"
log_dir: logs
timezone: Asia/Shanghai
gmtrade_endpoint: api.myquant.cn:9000
```

`src/gmtrade_live/precision.py`

```python
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


def normalize_price(value: float | Decimal) -> Decimal:
    """标准化价格为 3 位小数（A 股最小变动 0.01 元）"""
    return Decimal(str(value)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def normalize_amount(value: float | Decimal) -> Decimal:
    """标准化金额为 2 位小数"""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def normalize_ratio(value: float | Decimal) -> Decimal:
    """标准化比例为 4 位小数（如 0.0500 表示 5%）"""
    return Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
```

`tests/unit/test_precision.py`

```python
from decimal import Decimal

from gmtrade_live.precision import normalize_amount, normalize_price, normalize_ratio


def test_normalize_price_rounds_to_three_decimals() -> None:
    assert normalize_price(10.123456) == Decimal("10.123")
    assert normalize_price(10.1235) == Decimal("10.124")  # 四舍五入
    assert normalize_price(Decimal("10.123456")) == Decimal("10.123")


def test_normalize_amount_rounds_to_two_decimals() -> None:
    assert normalize_amount(1000.5678) == Decimal("1000.57")
    assert normalize_amount(1000.565) == Decimal("1000.57")  # 四舍五入
    assert normalize_amount(Decimal("1000.5678")) == Decimal("1000.57")


def test_normalize_ratio_rounds_to_four_decimals() -> None:
    assert normalize_ratio(0.05) == Decimal("0.0500")
    assert normalize_ratio(0.123456) == Decimal("0.1235")
    assert normalize_ratio(Decimal("0.123456")) == Decimal("0.1235")
```

- [ ] **Step 4: Run the precision tests and verify they pass**

Run:

```powershell
conda run -n test pytest tests/unit/test_precision.py -v
```

Expected: PASS. All precision normalization functions work correctly.

- [ ] **Step 5: Run the config and runtime tests again and verify they pass**

Run:

```powershell
conda run -n test pytest tests/unit/test_config.py tests/unit/test_runtime.py -v
```

Expected: PASS. Config parsing, environment-variable resolution, log creation, and session-state calculation are green.

- [ ] **Step 6: Commit the infrastructure baseline**

```powershell
git add config/sim_account.example.yaml src/gmtrade_live/errors.py src/gmtrade_live/config.py src/gmtrade_live/logging_setup.py src/gmtrade_live/session.py src/gmtrade_live/precision.py tests/unit/test_config.py tests/unit/test_runtime.py tests/unit/test_precision.py
git commit -m "feat: add config, runtime infrastructure, and data precision normalization for m0"
```

### Task 3: Add Internal Models, Gateway Protocols, And The M0 Application Service

**Files:**
- Create: `src/gmtrade_live/models.py`
- Create: `src/gmtrade_live/gateways/__init__.py`
- Create: `src/gmtrade_live/gateways/protocols.py`
- Create: `src/gmtrade_live/services/__init__.py`
- Create: `src/gmtrade_live/services/m0_connectivity.py`
- Test: `tests/integration/test_m0_connectivity_service.py`

- [ ] **Step 1: Write the failing integration test for the M0 service**

```python
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

from gmtrade_live.config import AppConfig
from gmtrade_live.models import CashSnapshot, PositionSnapshot, QuoteSnapshot
from gmtrade_live.services.m0_connectivity import ConnectivityCheckService
from gmtrade_live.session import TradingSessionState


class FakeTradeGateway:
    def connect(self, config: AppConfig) -> None:
        self.account_id = config.account_id

    def get_cash(self, account_id: str) -> CashSnapshot:
        return CashSnapshot(
            account_id=account_id,
            available_cash=Decimal("100000.00"),
            market_value=Decimal("12000.00"),
            total_asset=Decimal("112000.00"),
            update_time=datetime(2026, 4, 8, 10, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
        )

    def get_positions(self, account_id: str) -> list[PositionSnapshot]:
        return [
            PositionSnapshot(
                symbol="SHSE.600000",
                exchange="SHSE",
                volume=100,
                available_volume=100,
                cost_price=Decimal("10.01"),
                last_update_time=datetime(
                    2026,
                    4,
                    8,
                    10,
                    1,
                    tzinfo=ZoneInfo("Asia/Shanghai"),
                ),
            )
        ]


class FakeMarketGateway:
    def connect(self, token: str) -> None:
        self.token = token

    def get_quotes(self, symbols: list[str]) -> list[QuoteSnapshot]:
        return [
            QuoteSnapshot(
                symbol=symbol,
                last_price=Decimal("10.15"),
                quote_time=datetime(2026, 4, 8, 10, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
                source="gm.current",
            )
            for symbol in symbols
        ]


def test_connectivity_service_reads_cash_positions_and_quotes(tmp_path: Path) -> None:
    config = AppConfig(
        account_id="demo-account",
        token="demo-token",
        strategy_name="gmtrade-live-m0",
        poll_interval_seconds=5,
        take_profit_ratio=Decimal("0.05"),
        stop_loss_ratio=Decimal("0.03"),
        trade_session_start="09:30:00",
        trade_session_end="15:00:00",
        log_dir=tmp_path,
        timezone="Asia/Shanghai",
        gmtrade_endpoint="api.myquant.cn:9000",
    )
    logger = logging.getLogger("gmtrade-live-m0-test")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())

    service = ConnectivityCheckService(
        trade_gateway=FakeTradeGateway(),
        market_gateway=FakeMarketGateway(),
        logger=logger,
    )

    report = service.run(config=config, session_state=TradingSessionState.TRADING)

    assert report.account_id == "demo-account"
    assert report.session_state == "trading"
    assert report.cash.available_cash == Decimal("100000.00")
    assert len(report.positions) == 1
    assert report.positions[0].symbol == "SHSE.600000"
    assert len(report.quotes) == 1
    assert report.quotes[0].last_price == Decimal("10.15")
```

- [ ] **Step 2: Run the integration test and verify it fails**

Run:

```powershell
conda run -n test pytest tests/integration/test_m0_connectivity_service.py -v
```

Expected: FAIL with `ModuleNotFoundError` for `gmtrade_live.models` or `gmtrade_live.services`.

- [ ] **Step 3: Implement the internal models, gateway protocols, and M0 service**

`src/gmtrade_live/models.py`

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class CashSnapshot:
    account_id: str
    available_cash: Decimal
    market_value: Decimal
    total_asset: Decimal
    update_time: datetime


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    symbol: str
    exchange: str
    volume: int
    available_volume: int
    cost_price: Decimal
    last_update_time: datetime


@dataclass(frozen=True, slots=True)
class QuoteSnapshot:
    symbol: str
    last_price: Decimal
    quote_time: datetime
    source: str


@dataclass(frozen=True, slots=True)
class ConnectivityReport:
    account_id: str
    session_state: str
    cash: CashSnapshot
    positions: tuple[PositionSnapshot, ...]
    quotes: tuple[QuoteSnapshot, ...]
```

`src/gmtrade_live/gateways/__init__.py`

```python
__all__ = []
```

`src/gmtrade_live/gateways/protocols.py`

```python
from __future__ import annotations

from typing import Protocol

from gmtrade_live.config import AppConfig
from gmtrade_live.models import CashSnapshot, PositionSnapshot, QuoteSnapshot


class TradeGateway(Protocol):
    def connect(self, config: AppConfig) -> None:
        ...

    def get_cash(self, account_id: str) -> CashSnapshot:
        ...

    def get_positions(self, account_id: str) -> list[PositionSnapshot]:
        ...


class MarketGateway(Protocol):
    def connect(self, token: str) -> None:
        ...

    def get_quotes(self, symbols: list[str]) -> list[QuoteSnapshot]:
        ...
```

`src/gmtrade_live/services/__init__.py`

```python
__all__ = []
```

`src/gmtrade_live/services/m0_connectivity.py`

```python
from __future__ import annotations

import logging

from gmtrade_live.config import AppConfig
from gmtrade_live.gateways.protocols import MarketGateway, TradeGateway
from gmtrade_live.models import ConnectivityReport
from gmtrade_live.session import TradingSessionState


class ConnectivityCheckService:
    def __init__(
        self,
        *,
        trade_gateway: TradeGateway,
        market_gateway: MarketGateway,
        logger: logging.Logger,
    ) -> None:
        self._trade_gateway = trade_gateway
        self._market_gateway = market_gateway
        self._logger = logger

    def run(
        self,
        *,
        config: AppConfig,
        session_state: TradingSessionState,
    ) -> ConnectivityReport:
        self._trade_gateway.connect(config)
        self._market_gateway.connect(config.token)

        cash = self._trade_gateway.get_cash(config.account_id)
        positions = self._trade_gateway.get_positions(config.account_id)
        symbols = [item.symbol for item in positions if item.available_volume > 0]
        quotes = self._market_gateway.get_quotes(symbols)

        self._logger.info(
            "m0_connectivity_success account_id=%s session_state=%s positions=%s quotes=%s",
            config.account_id,
            session_state.value,
            len(positions),
            len(quotes),
        )

        return ConnectivityReport(
            account_id=config.account_id,
            session_state=session_state.value,
            cash=cash,
            positions=tuple(positions),
            quotes=tuple(quotes),
        )
```

- [ ] **Step 4: Run the integration test again and verify it passes**

Run:

```powershell
conda run -n test pytest tests/integration/test_m0_connectivity_service.py -v
```

Expected: PASS. The service returns one cash snapshot, one position, and one quote.

- [ ] **Step 5: Commit the M0 service core**

```powershell
git add src/gmtrade_live/models.py src/gmtrade_live/gateways/__init__.py src/gmtrade_live/gateways/protocols.py src/gmtrade_live/services/__init__.py src/gmtrade_live/services/m0_connectivity.py tests/integration/test_m0_connectivity_service.py
git commit -m "feat: add m0 connectivity service core"
```

### Task 3.5: Add Position State Manager (Memory Version)

**Files:**
- Create: `src/gmtrade_live/state.py`
- Test: `tests/unit/test_state.py`

- [ ] **Step 1: Write the failing state manager tests**

```python
from datetime import datetime
from decimal import Decimal

from gmtrade_live.state import PositionState, PositionStateManager, PositionStateSnapshot


def test_state_manager_returns_idle_for_new_symbol() -> None:
    """测试新标的默认返回 idle 状态"""
    manager = PositionStateManager(logger=None)
    
    snapshot = manager.get_state("SHSE.600036")
    
    assert snapshot.symbol == "SHSE.600036"
    assert snapshot.state == PositionState.idle


def test_state_manager_updates_state() -> None:
    """测试状态更新"""
    manager = PositionStateManager(logger=None)
    
    manager.update_state(
        "SHSE.600036",
        PositionState.triggered,
        trigger_type="take_profit",
        trigger_price=Decimal("10.50")
    )
    
    snapshot = manager.get_state("SHSE.600036")
    assert snapshot.state == PositionState.triggered
    assert snapshot.trigger_type == "take_profit"
    assert snapshot.trigger_price == Decimal("10.50")


def test_state_manager_detects_open_orders() -> None:
    """测试未完成订单检测"""
    manager = PositionStateManager(logger=None)
    
    # 初始状态：没有未完成订单
    assert manager.has_open_order("SHSE.600036") is False
    
    # 提交订单后：有未完成订单
    manager.update_state("SHSE.600036", PositionState.submitted, order_id="ORDER_123")
    assert manager.has_open_order("SHSE.600036") is True
    
    # 部分成交：仍然有未完成订单
    manager.update_state("SHSE.600036", PositionState.partially_filled)
    assert manager.has_open_order("SHSE.600036") is True
    
    # 全部成交：没有未完成订单
    manager.update_state("SHSE.600036", PositionState.filled)
    assert manager.has_open_order("SHSE.600036") is False


def test_state_manager_isolates_symbols() -> None:
    """测试多标的状态隔离"""
    manager = PositionStateManager(logger=None)
    
    manager.update_state("SHSE.600036", PositionState.submitted, order_id="ORDER_1")
    manager.update_state("SHSE.600000", PositionState.triggered)
    
    # 两个标的的状态互不影响
    assert manager.get_state("SHSE.600036").state == PositionState.submitted
    assert manager.get_state("SHSE.600000").state == PositionState.triggered
    
    # 一个标的有未完成订单，另一个没有
    assert manager.has_open_order("SHSE.600036") is True
    assert manager.has_open_order("SHSE.600000") is False
```

- [ ] **Step 2: Run the state manager tests and verify they fail**

Run:

```powershell
conda run -n test pytest tests/unit/test_state.py -v
```

Expected: FAIL with `ModuleNotFoundError` for `gmtrade_live.state`.

- [ ] **Step 3: Implement the position state manager**

`src/gmtrade_live/state.py`

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from logging import Logger


class PositionState(str, Enum):
    """持仓标的的统一状态"""
    idle = "idle"                          # 有持仓，未触发
    triggered = "triggered"                # 已触发，待提交
    submitting = "submitting"              # 正在提交
    submitted = "submitted"                # 已提交，等待回报
    partially_filled = "partially_filled"  # 部分成交
    filled = "filled"                      # 全部成交
    cancelled = "cancelled"                # 已撤单
    failed = "failed"                      # 失败


@dataclass
class PositionStateSnapshot:
    """持仓标的的状态快照"""
    symbol: str
    state: PositionState
    order_id: str | None = None           # 委托编号
    trigger_type: str | None = None       # 触发类型：take_profit / stop_loss
    trigger_price: Decimal | None = None  # 触发价格
    requested_volume: int = 0             # 请求卖出数量
    filled_volume: int = 0                # 已成交数量
    last_update_time: datetime | None = None
    message: str = ""                     # 说明或错误原因


class PositionStateManager:
    """集中管理所有持仓标的的状态（内存版本）"""
    
    def __init__(self, logger: Logger | None):
        self._logger = logger
        self._cache: dict[str, PositionStateSnapshot] = {}
    
    def get_state(self, symbol: str) -> PositionStateSnapshot:
        """获取标的当前状态"""
        if symbol not in self._cache:
            return PositionStateSnapshot(symbol=symbol, state=PositionState.idle)
        return self._cache[symbol]
    
    def update_state(
        self,
        symbol: str,
        new_state: PositionState,
        **kwargs
    ) -> None:
        """更新标的状态"""
        snapshot = self.get_state(symbol)
        old_state = snapshot.state
        
        # 更新状态
        snapshot.state = new_state
        snapshot.last_update_time = datetime.now()
        
        # 更新其他字段
        for key, value in kwargs.items():
            if hasattr(snapshot, key):
                setattr(snapshot, key, value)
        
        # 更新内存缓存
        self._cache[symbol] = snapshot
        
        # 记录日志（结构化格式）
        if self._logger:
            self._logger.info(
                f"state_change symbol={symbol} old_state={old_state.value} "
                f"new_state={new_state.value} {' '.join(f'{k}={v}' for k, v in kwargs.items())}"
            )
    
    def has_open_order(self, symbol: str) -> bool:
        """判断是否有未完成订单"""
        state = self.get_state(symbol).state
        return state in [PositionState.submitted, PositionState.partially_filled]
```

- [ ] **Step 4: Run the state manager tests again and verify they pass**

Run:

```powershell
conda run -n test pytest tests/unit/test_state.py -v
```

Expected: PASS. All state manager tests are green.

- [ ] **Step 5: Commit the state manager**

```powershell
git add src/gmtrade_live/state.py tests/unit/test_state.py
git commit -m "feat: add position state manager (memory version) for m0"
```

### Task 4: Add Official GM Adapters With Precision Normalization, Real Wiring, And M0 Smoke Verification

**Files:**
- Create: `src/gmtrade_live/gateways/gmtrade_trade_gateway.py`
- Create: `src/gmtrade_live/gateways/gm_market_gateway.py`
- Create: `src/gmtrade_live/bootstrap.py`
- Test: `tests/unit/test_official_gateways.py`
- Verify: `main.py`
- Verify: `config/sim_account.example.yaml`

- [ ] **Step 1: Write the failing official-adapter tests**

```python
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from gmtrade_live.config import AppConfig
from gmtrade_live.gateways.gm_market_gateway import GMCurrentQuoteGateway
from gmtrade_live.gateways.gmtrade_trade_gateway import GMTradeQueryGateway


class FakeGMTradeApi:
    def __init__(self) -> None:
        self.token = None
        self.endpoint = None
        self.logged_in_account = None

    def set_token(self, token: str) -> None:
        self.token = token

    def set_endpoint(self, endpoint: str) -> None:
        self.endpoint = endpoint

    def account(self, account_id: str, account_alias: str) -> dict[str, str]:
        return {"account_id": account_id, "account_alias": account_alias}

    def login(self, account_object: dict[str, str]) -> None:
        self.logged_in_account = account_object

    def get_cash(self, account_id: str | None = None) -> dict[str, object]:
        return {
            "account_id": account_id,
            "available": 20000.0,
            "market_value": 5000.0,
            "nav": 25000.0,
            "updated_at": datetime(2026, 4, 8, 10, 5, tzinfo=ZoneInfo("Asia/Shanghai")),
        }

    def get_position(self, account_id: str | None = None) -> list[dict[str, object]]:
        return [
            {
                "symbol": "SHSE.600000",
                "volume": 100,
                "available": 100,
                "cost": 1000.0,
                "updated_at": datetime(
                    2026,
                    4,
                    8,
                    10,
                    5,
                    tzinfo=ZoneInfo("Asia/Shanghai"),
                ),
            }
        ]


class FakeGMApi:
    def __init__(self) -> None:
        self.token = None

    def set_token(self, token: str) -> None:
        self.token = token

    def current(self, symbols: list[str], fields: str = "") -> list[dict[str, object]]:
        return [
            {
                "symbol": symbol,
                "price": 10.25,
                "created_at": datetime(
                    2026,
                    4,
                    8,
                    10,
                    5,
                    tzinfo=ZoneInfo("Asia/Shanghai"),
                ),
            }
            for symbol in symbols
        ]


def _build_config() -> AppConfig:
    return AppConfig(
        account_id="demo-account",
        token="demo-token",
        strategy_name="gmtrade-live-m0",
        poll_interval_seconds=5,
        take_profit_ratio=Decimal("0.05"),
        stop_loss_ratio=Decimal("0.03"),
        trade_session_start="09:30:00",
        trade_session_end="15:00:00",
        log_dir=Path("logs"),
        timezone="Asia/Shanghai",
        gmtrade_endpoint="api.myquant.cn:9000",
    )


def test_gmtrade_gateway_connects_and_maps_query_objects() -> None:
    api = FakeGMTradeApi()
    gateway = GMTradeQueryGateway(api_module=api)
    config = _build_config()

    gateway.connect(config)
    cash = gateway.get_cash(config.account_id)
    positions = gateway.get_positions(config.account_id)

    assert api.token == "demo-token"
    assert api.endpoint == "api.myquant.cn:9000"
    # 验证金额精度（2 位小数）
    assert cash.total_asset == Decimal("25000.00")
    assert cash.available_cash == Decimal("20000.00")
    assert cash.market_value == Decimal("5000.00")
    # 验证持仓数据
    assert positions[0].symbol == "SHSE.600000"
    assert positions[0].available_volume == 100
    # 验证价格精度（3 位小数）
    assert positions[0].cost_price == Decimal("10.000")


def test_gm_market_gateway_reads_quotes_from_current() -> None:
    api = FakeGMApi()
    gateway = GMCurrentQuoteGateway(api_module=api)

    gateway.connect("demo-token")
    quotes = gateway.get_quotes(["SHSE.600000"])

    assert api.token == "demo-token"
    assert quotes[0].symbol == "SHSE.600000"
    # 验证价格精度（3 位小数）
    assert quotes[0].last_price == Decimal("10.250")
    assert quotes[0].source == "gm.current"
    assert quotes[0].last_price == Decimal("10.25")
    assert quotes[0].source == "gm.current"
```

- [ ] **Step 2: Run the official-adapter tests and verify they fail**

Run:

```powershell
conda run -n test pytest tests/unit/test_official_gateways.py -v
```

Expected: FAIL with `ModuleNotFoundError` for the adapter modules.

- [ ] **Step 3: Implement the official adapters and real bootstrap wiring**

`src/gmtrade_live/gateways/gmtrade_trade_gateway.py`

```python
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import importlib
from typing import Any

from gmtrade_live.config import AppConfig
from gmtrade_live.errors import ServiceError
from gmtrade_live.models import CashSnapshot, PositionSnapshot
from gmtrade_live.precision import normalize_amount, normalize_price


class GMTradeQueryGateway:
    def __init__(self, api_module: Any | None = None) -> None:
        self._api = api_module or importlib.import_module("gmtrade.api")

    def connect(self, config: AppConfig) -> None:
        self._api.set_token(config.token)
        self._api.set_endpoint(config.gmtrade_endpoint)
        account_object = self._api.account(
            account_id=config.account_id,
            account_alias=config.strategy_name,
        )
        self._api.login(account_object)

    def get_cash(self, account_id: str) -> CashSnapshot:
        raw = self._api.get_cash(account_id=account_id)
        if not raw:
            raise ServiceError(
                code="gmtrade.empty_cash",
                message="掘金未返回资金对象",
                retryable=True,
                context={"account_id": account_id},
            )

        return CashSnapshot(
            account_id=str(raw["account_id"]),
            available_cash=normalize_amount(raw["available"]),
            market_value=normalize_amount(raw["market_value"]),
            total_asset=normalize_amount(raw["nav"]),
            update_time=_as_datetime(raw["updated_at"]),
        )

    def get_positions(self, account_id: str) -> list[PositionSnapshot]:
        rows = self._api.get_position(account_id=account_id) or []
        results: list[PositionSnapshot] = []
        for row in rows:
            symbol = str(row["symbol"])
            # 持仓成本需要除以数量得到单价
            cost_per_share = float(row["cost"]) / int(row["volume"]) if int(row["volume"]) > 0 else 0.0
            results.append(
                PositionSnapshot(
                    symbol=symbol,
                    exchange=symbol.split(".", maxsplit=1)[0] if "." in symbol else "",
                    volume=int(row["volume"]),
                    available_volume=int(row["available"]),
                    cost_price=normalize_price(cost_per_share),
                    last_update_time=_as_datetime(row["updated_at"]),
                )
            )
        return results


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    raise ServiceError(
        code="gmtrade.invalid_datetime",
        message="掘金返回的时间字段格式不合法",
        retryable=True,
        context={"value": str(value)},
    )
```

`src/gmtrade_live/gateways/gm_market_gateway.py`

```python
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import importlib
from typing import Any

from gmtrade_live.errors import ServiceError
from gmtrade_live.models import QuoteSnapshot
from gmtrade_live.precision import normalize_price


class GMCurrentQuoteGateway:
    def __init__(self, api_module: Any | None = None) -> None:
        self._api = api_module or importlib.import_module("gm.api")

    def connect(self, token: str) -> None:
        self._api.set_token(token)

    def get_quotes(self, symbols: list[str]) -> list[QuoteSnapshot]:
        if not symbols:
            return []

        rows = self._api.current(symbols=symbols, fields="symbol,price,created_at")
        results: list[QuoteSnapshot] = []
        for row in rows:
            if "symbol" not in row or "price" not in row or "created_at" not in row:
                raise ServiceError(
                    code="gm.invalid_quote_payload",
                    message="行情快照字段缺失",
                    retryable=True,
                    context={"payload": str(row)},
                )
            results.append(
                QuoteSnapshot(
                    symbol=str(row["symbol"]),
                    last_price=normalize_price(row["price"]),
                    quote_time=_as_datetime(row["created_at"]),
                    source="gm.current",
                )
            )
        return results


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    raise ServiceError(
        code="gm.invalid_datetime",
        message="行情时间字段格式不合法",
        retryable=True,
        context={"value": str(value)},
    )
```

`src/gmtrade_live/bootstrap.py`

```python
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from gmtrade_live.config import load_config
from gmtrade_live.gateways.gm_market_gateway import GMCurrentQuoteGateway
from gmtrade_live.gateways.gmtrade_trade_gateway import GMTradeQueryGateway
from gmtrade_live.logging_setup import setup_logging
from gmtrade_live.services.m0_connectivity import ConnectivityCheckService
from gmtrade_live.session import resolve_trading_session


def run_m0_connectivity_check(config_path: Path) -> int:
    config = load_config(config_path)
    logger = setup_logging(config.strategy_name, config.log_dir)

    # 输出心跳日志（结构化格式）
    logger.info(f"heartbeat round=1 status=starting config={config_path}")

    session_state = resolve_trading_session(
        datetime.now(tz=ZoneInfo(config.timezone)),
        start_text=config.trade_session_start,
        end_text=config.trade_session_end,
        timezone_name=config.timezone,
    )

    service = ConnectivityCheckService(
        trade_gateway=GMTradeQueryGateway(),
        market_gateway=GMCurrentQuoteGateway(),
        logger=logger,
    )
    report = service.run(config=config, session_state=session_state)

    # 输出结果（JSON 格式）
    print(
        json.dumps(
            {
                "account_id": report.account_id,
                "session_state": report.session_state,
                "available_cash": str(report.cash.available_cash),
                "position_count": len(report.positions),
                "quote_count": len(report.quotes),
            },
            ensure_ascii=False,
        )
    )
    
    # 输出完成心跳日志
    logger.info(
        f"heartbeat round=1 status=completed positions={len(report.positions)} "
        f"quotes={len(report.quotes)}"
    )
    
    return 0
```
from gmtrade_live.logging_setup import setup_logging
from gmtrade_live.services.m0_connectivity import ConnectivityCheckService
from gmtrade_live.session import resolve_trading_session


def run_m0_connectivity_check(config_path: Path) -> int:
    config = load_config(config_path)
    logger = setup_logging(config.strategy_name, config.log_dir)

    session_state = resolve_trading_session(
        datetime.now(tz=ZoneInfo(config.timezone)),
        start_text=config.trade_session_start,
        end_text=config.trade_session_end,
        timezone_name=config.timezone,
    )

    service = ConnectivityCheckService(
        trade_gateway=GMTradeQueryGateway(),
        market_gateway=GMCurrentQuoteGateway(),
        logger=logger,
    )
    report = service.run(config=config, session_state=session_state)

    print(
        json.dumps(
            {
                "account_id": report.account_id,
                "session_state": report.session_state,
                "available_cash": str(report.cash.available_cash),
                "position_count": len(report.positions),
                "quote_count": len(report.quotes),
            },
            ensure_ascii=False,
        )
    )
    return 0
```

- [ ] **Step 4: Run the adapter tests again and verify they pass**

Run:

```powershell
conda run -n test pytest tests/unit/test_official_gateways.py -v
```

Expected: PASS. Both official wrapper classes map fake SDK payloads into internal snapshots.

- [ ] **Step 5: Install the package into the `test` environment**

Run:

```powershell
conda run -n test python -m pip install -e .
```

Expected: editable install succeeds, and `PyYAML`, `gm`, `gmtrade`, `pytest` are available in the `test` environment.

- [ ] **Step 6: Run the full automated test set**

Run:

```powershell
conda run -n test pytest tests/unit tests/integration -v
```

Expected: PASS. All unit and integration tests are green.

- [ ] **Step 7: Create the local runtime config from the checked-in example**

Run:

```powershell
Copy-Item config\sim_account.example.yaml config\sim_account.yaml
```

Expected: `config/sim_account.yaml` exists locally and remains untracked because of `.gitignore`.

- [ ] **Step 8: Export the real GM credentials into the current PowerShell session**

Run:

```powershell
$env:GM_ACCOUNT_ID = Read-Host "GM_ACCOUNT_ID"
$env:GM_TOKEN = Read-Host "GM_TOKEN"
```

Expected: the environment variables are available to the current terminal session only.

- [ ] **Step 9: Run the real M0 smoke command**

Run:

```powershell
conda run -n test python main.py --config config/sim_account.yaml
```

Expected:

- console prints one JSON line like `{"account_id":"...","session_state":"trading","available_cash":"...","position_count":1,"quote_count":1}`
- `logs/runtime.log` is created
- the log file includes `m0_connectivity_success`

- [ ] **Step 10: Capture the M0 verification evidence**

Run:

```powershell
Get-Content logs\runtime.log -Tail 20
```

Expected: the latest lines include the connectivity success record with account ID, session state, positions count, and quote count.

- [ ] **Step 11: Commit the real wiring**

```powershell
git add src/gmtrade_live/gateways/gmtrade_trade_gateway.py src/gmtrade_live/gateways/gm_market_gateway.py src/gmtrade_live/bootstrap.py tests/unit/test_official_gateways.py
git commit -m "feat: wire official gm adapters for m0"
```

## Self-Review

### Spec coverage

- 基础设施层：covered by Tasks 1-2 through CLI, config validation, structured logging with heartbeat, and session-state control.
- 数据接入层：covered by Task 4 through official `gmtrade` / `gm` adapters with precision normalization.
- 状态管理：covered by Task 3.5 through memory-based PositionStateManager.
- 数据精度：covered by Task 2 through precision normalization functions (price 3 decimals, amount 2 decimals).
- 测试与质量保障：covered by every task through TDD and by Task 4 full verification commands.
- `M0` 完成定义：covered by Task 4 smoke run, which verifies账号连通、资金读取、持仓读取、行情读取。

### New additions based on updated specs

- **Data precision normalization** - All prices, amounts, and ratios are normalized to standard precision in gateways.
- **Position state manager** - Memory-based state manager for tracking position states (idle, triggered, submitted, etc.).
- **Structured logging** - Heartbeat logs and event logs use key=value format for easy parsing.
- **Precision tests** - Unit tests verify that normalization functions work correctly.
- **State manager tests** - Unit tests verify state isolation, open order detection, and state transitions.

### Placeholder scan

- No `TBD`, `TODO`, or “implement later” text remains.
- The only runtime-specific values are real credentials exported through environment variables, because secrets cannot be committed into the repository.

### Type consistency

- `AppConfig`, `CashSnapshot`, `PositionSnapshot`, `QuoteSnapshot`, and `ConnectivityReport` are defined before later tasks use them.
- The gateway method names are consistent end-to-end: `connect`, `get_cash`, `get_positions`, `get_quotes`.
- All numeric values use `Decimal` with appropriate precision (price: 3 decimals, amount: 2 decimals, ratio: 4 decimals).
