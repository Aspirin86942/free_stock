# Market Analysis Scheduler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为当前 Windows 本机运行环境新增“官方日线补数 -> MySQL -> 最近 10 个交易日盘后分析 -> 飞书推送 -> `19:15` 定时调度”的完整链路，并保持现有自动交易入口可继续使用。

**Architecture:** 保留 [main.py](D:/Program_python/free_stock/main.py) 作为自动交易入口，同时引入一个独立的 `scheduler.py` 入口。配置层升级为“单 YAML、多 section”，但继续保留 `load_config()` 兼容自动交易主链；盘后市场分析链路新增官方历史日线网关、MySQL 仓储、日线补数服务、四类 analyzer、飞书通知服务和一次性 `market_close_job`，调度器只负责触发与重试，不承载业务逻辑。

**Tech Stack:** Python 3.10+, `Decimal`, `dataclasses`, `argparse`, `logging`, `zoneinfo`, `pandas`, `APScheduler`, `PyMySQL`, `requests`, 现有 `GMTradeGateway`, `GMCurrentQuoteGateway`, `app_runner.py`, `config.py`, `logging_setup.py`

---

## Planned File Structure

**Create:**
- `scheduler.py` - Windows 本机统一调度入口，支持常驻调度和手动触发盘后任务。
- `src/gmtrade_live/market_models.py` - 市场分析链路的原始日线、checkpoint、指标结果、日报结果 dataclass。
- `src/gmtrade_live/runtime_scheduler.py` - 运行时调度编排，负责注册 `market analysis job`、重试和日志。
- `src/gmtrade_live/gateways/gm_history_market_gateway.py` - 官方历史市场数据网关，封装交易日历与指定交易日全市场日线快照读取。
- `src/gmtrade_live/repositories/__init__.py` - 仓储包初始化。
- `src/gmtrade_live/repositories/mysql_market_repository.py` - MySQL DDL、upsert、checkpoint、分析数据读取。
- `src/gmtrade_live/services/market_data_sync_service.py` - 三年全量回补与缺口补数服务。
- `src/gmtrade_live/services/market_breadth_analyzer.py` - 市场整体指标 analyzer。
- `src/gmtrade_live/services/market_profit_effect_analyzer.py` - 赚钱效应 analyzer。
- `src/gmtrade_live/services/market_tolerance_analyzer.py` - 容错指标 analyzer。
- `src/gmtrade_live/services/market_emotion_analyzer.py` - 情绪指标 analyzer。
- `src/gmtrade_live/services/market_close_report_builder.py` - 汇总最近 10 个交易日逐日明细表和摘要。
- `src/gmtrade_live/services/feishu_notification_service.py` - 飞书 webhook 发送服务。
- `src/gmtrade_live/services/market_close_job.py` - 一次性盘后任务编排：补数 -> 分析 -> 飞书。
- `tests/unit/test_gm_history_market_gateway.py` - 历史市场网关测试。
- `tests/unit/test_mysql_market_repository.py` - MySQL 仓储 SQL / checkpoint 测试。
- `tests/unit/test_market_data_sync_service.py` - 补数服务测试。
- `tests/unit/test_market_breadth_analyzer.py` - 市场整体指标测试。
- `tests/unit/test_market_profit_effect_analyzer.py` - 赚钱效应测试。
- `tests/unit/test_market_tolerance_analyzer.py` - 容错指标测试。
- `tests/unit/test_market_emotion_analyzer.py` - 情绪指标测试。
- `tests/unit/test_market_close_report_builder.py` - 最近 10 个交易日明细表测试。
- `tests/unit/test_feishu_notification_service.py` - 飞书发送测试。
- `tests/unit/test_market_close_job.py` - 盘后任务编排测试。
- `tests/unit/test_runtime_scheduler.py` - 调度器注册、重试与 CLI 入口测试。
- `docs/market-analysis-runtime.md` - 盘后分析和 scheduler 运行说明。

**Modify:**
- `pyproject.toml` - 增加 `APScheduler`、`PyMySQL`、`requests`、`pandas` 依赖。
- `src/gmtrade_live/config.py` - 增加嵌套配置 dataclass、`load_runtime_config()`，并保持 `load_config()` 兼容自动交易主链。
- `src/gmtrade_live/gateways/protocols.py` - 增加历史市场网关协议。
- `src/gmtrade_live/app_runner.py` - 新增 `run_market_close_once()`，供 scheduler 手动/定时调用。
- `config/sim_account.example.yaml` - 改为单 YAML、多 section，默认 `report_time: "19:15"`。
- `tests/unit/test_config.py` - 新增嵌套配置和兼容加载断言。
- `AGENTS.md` - 增补 `scheduler.py`、`19:15` 盘后分析命令和说明。

**Read-only references:**
- `docs/superpowers/specs/2026-04-14-market-analysis-scheduler-design.md`
- `src/gmtrade_live/app_runner.py`
- `src/gmtrade_live/config.py`
- `src/gmtrade_live/gateways/protocols.py`
- `src/gmtrade_live/logging_setup.py`
- `tests/unit/test_config.py`

## Scope Guard

- 当前计划只实现“市场分析 scheduler”完整闭环，不实现盘中自动交易的启停策略；`trade.enabled` 仅保留为配置入口和未来扩展点。
- 盘后分析固定基于官方日 K 与 MySQL 事实表，不回到分钟 K，也不在首版引入分析结果表。
- 盘后调度时间按用户确认改为 `19:15`，因为官方日线数据通常在晚间更新，`15:15` 无法稳定拿到完整当日日 K。
- 所有统计统一排除 `ST`、停牌、当日无成交股票；热门股按“昨日收盘价 > 10、昨日换手率 > 10%、上市超过 250 个交易日、非 ST”定义。
- 飞书只发最近一个已完成交易日的日报，不补发历史消息。

### Task 1: 重构配置层并引入运行时依赖

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/gmtrade_live/config.py`
- Modify: `config/sim_account.example.yaml`
- Modify: `tests/unit/test_config.py`

- [ ] **Step 1: 先写嵌套配置的失败测试，锁定兼容行为**

```python
# tests/unit/test_config.py
from decimal import Decimal
from pathlib import Path

from gmtrade_live.config import AppConfig, RuntimeConfig, load_config, load_runtime_config


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
                "  log_dir: logs",
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
            ]
        ),
        encoding="utf-8",
    )

    runtime = load_runtime_config(config_file)

    assert isinstance(runtime, RuntimeConfig)
    assert runtime.gm.token == "demo-token"
    assert runtime.trade.poll_interval_seconds == 5
    assert runtime.trade.take_profit_ratio == Decimal("0.015")
    assert runtime.market_analysis.report_time == "19:15"
    assert runtime.mysql.port == 3306


def test_load_config_keeps_auto_sell_compatibility_for_nested_yaml(
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
        Path("config/sim_account.example.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    config = load_config(config_file)

    assert isinstance(config, AppConfig)
    assert config.account_id == "demo-account"
    assert config.gmtrade_endpoint == "127.0.0.1:7001"
    assert config.sell_quantity_ratio == Decimal("0.02")
```

- [ ] **Step 2: 运行配置测试，确认当前实现尚不支持嵌套结构**

Run: `conda run -n stock_analysis pytest tests/unit/test_config.py -q`
Expected: 新增测试失败，至少出现 `AttributeError`、`config.missing_field` 或 `load_runtime_config` 未定义。

- [ ] **Step 3: 以最小改动实现嵌套运行时配置，并保留自动交易兼容加载**

```python
# src/gmtrade_live/config.py
@dataclass(frozen=True, slots=True)
class GMConfig:
    token: str
    endpoint: str
    timezone: str


@dataclass(frozen=True, slots=True)
class TradeConfig:
    enabled: bool
    account_id: str
    strategy_name: str
    poll_interval_seconds: int
    take_profit_ratio: Decimal
    stop_loss_ratio: Decimal
    sell_quantity_ratio: Decimal
    market_session_mode: str
    log_dir: Path


@dataclass(frozen=True, slots=True)
class MarketAnalysisConfig:
    enabled: bool
    universe: str
    history_years: int
    recent_trade_days: int
    report_time: str


@dataclass(frozen=True, slots=True)
class MySQLConfig:
    host: str
    port: int
    database: str
    user: str
    password: str


@dataclass(frozen=True, slots=True)
class FeishuConfig:
    webhook: str


@dataclass(frozen=True, slots=True)
class SchedulerConfig:
    enabled: bool
    retry_interval_minutes: int
    max_attempts: int


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    gm: GMConfig
    trade: TradeConfig
    market_analysis: MarketAnalysisConfig
    mysql: MySQLConfig
    feishu: FeishuConfig
    scheduler: SchedulerConfig
```

```python
def load_runtime_config(config_path: Path) -> RuntimeConfig:
    raw = _load_yaml_dict(config_path)
    resolved = _resolve_nested_env(raw)
    gm_raw = _require_dict(resolved, "gm")
    trade_raw = _require_dict(resolved, "trade")
    market_raw = _require_dict(resolved, "market_analysis")
    mysql_raw = _require_dict(resolved, "mysql")
    feishu_raw = _require_dict(resolved, "feishu")
    scheduler_raw = _require_dict(resolved, "scheduler")
    return RuntimeConfig(
        gm=GMConfig(
            token=str(gm_raw["token"]),
            endpoint=str(gm_raw.get("endpoint", "127.0.0.1:7001")),
            timezone=str(gm_raw.get("timezone", "Asia/Shanghai")),
        ),
        trade=TradeConfig(
            enabled=bool(trade_raw.get("enabled", False)),
            account_id=str(trade_raw["account_id"]),
            strategy_name=str(trade_raw["strategy_name"]),
            poll_interval_seconds=_parse_positive_int(trade_raw["poll_interval_seconds"], "trade.poll_interval_seconds"),
            take_profit_ratio=_parse_decimal(trade_raw["take_profit_ratio"], "trade.take_profit_ratio"),
            stop_loss_ratio=_parse_decimal(trade_raw["stop_loss_ratio"], "trade.stop_loss_ratio"),
            sell_quantity_ratio=_parse_sell_quantity_ratio(trade_raw["sell_quantity_ratio"], "trade.sell_quantity_ratio"),
            market_session_mode=_parse_market_session_mode(trade_raw["market_session_mode"], "trade.market_session_mode"),
            log_dir=Path(str(trade_raw["log_dir"])),
        ),
        market_analysis=MarketAnalysisConfig(
            enabled=bool(market_raw.get("enabled", True)),
            universe=str(market_raw["universe"]),
            history_years=_parse_positive_int(market_raw["history_years"], "market_analysis.history_years"),
            recent_trade_days=_parse_positive_int(market_raw["recent_trade_days"], "market_analysis.recent_trade_days"),
            report_time=str(market_raw["report_time"]),
        ),
        mysql=MySQLConfig(
            host=str(mysql_raw["host"]),
            port=_parse_positive_int(mysql_raw["port"], "mysql.port"),
            database=str(mysql_raw["database"]),
            user=str(mysql_raw["user"]),
            password=str(mysql_raw["password"]),
        ),
        feishu=FeishuConfig(webhook=str(feishu_raw["webhook"])),
        scheduler=SchedulerConfig(
            enabled=bool(scheduler_raw.get("enabled", True)),
            retry_interval_minutes=_parse_positive_int(scheduler_raw["retry_interval_minutes"], "scheduler.retry_interval_minutes"),
            max_attempts=_parse_positive_int(scheduler_raw["max_attempts"], "scheduler.max_attempts"),
        ),
    )


def load_config(config_path: Path) -> AppConfig:
    runtime = load_runtime_config(config_path)
    return AppConfig(
        account_id=runtime.trade.account_id,
        token=runtime.gm.token,
        strategy_name=runtime.trade.strategy_name,
        poll_interval_seconds=runtime.trade.poll_interval_seconds,
        take_profit_ratio=runtime.trade.take_profit_ratio,
        stop_loss_ratio=runtime.trade.stop_loss_ratio,
        sell_quantity_ratio=runtime.trade.sell_quantity_ratio,
        market_session_mode=runtime.trade.market_session_mode,
        log_dir=runtime.trade.log_dir,
        timezone=runtime.gm.timezone,
        gmtrade_endpoint=runtime.gm.endpoint,
    )
```

```toml
# pyproject.toml
dependencies = [
  "PyYAML>=6.0.2,<7.0.0",
  "gm==3.0.183",
  "APScheduler>=3.10,<4.0",
  "PyMySQL>=1.1,<2.0",
  "requests>=2.32,<3.0",
  "pandas>=2.2,<3.0",
]
```

```yaml
# config/sim_account.example.yaml
gm:
  token: ${GM_TOKEN}
  endpoint: 127.0.0.1:7001
  timezone: Asia/Shanghai
trade:
  enabled: false
  account_id: ${GM_ACCOUNT_ID}
  strategy_name: gmtrade-live-auto-sell
  poll_interval_seconds: 5
  take_profit_ratio: "0.015"
  stop_loss_ratio: "0.02"
  sell_quantity_ratio: "0.02"
  market_session_mode: a_share
  log_dir: logs
market_analysis:
  enabled: true
  universe: ashare_main_gem_star
  history_years: 3
  recent_trade_days: 10
  report_time: "19:15"
mysql:
  host: 127.0.0.1
  port: 3306
  database: market_data
  user: ${MYSQL_USER}
  password: ${MYSQL_PASSWORD}
feishu:
  webhook: ${FEISHU_WEBHOOK}
scheduler:
  enabled: true
  retry_interval_minutes: 10
  max_attempts: 3
```

- [ ] **Step 4: 跑配置测试和静态检查，确认兼容自动交易入口**

Run: `conda run -n stock_analysis pytest tests/unit/test_config.py -q`
Expected: PASS，新增嵌套配置测试通过，原有自动交易配置测试仍通过。

Run: `conda run -n stock_analysis ruff check src/gmtrade_live/config.py tests/unit/test_config.py pyproject.toml`
Expected: `All checks passed!`

- [ ] **Step 5: 提交配置与依赖脚手架**

```bash
git add pyproject.toml src/gmtrade_live/config.py config/sim_account.example.yaml tests/unit/test_config.py
git commit -m "feat(config): add runtime config for market analysis scheduler"
```

### Task 2: 新增历史市场网关与市场链路模型

**Files:**
- Create: `src/gmtrade_live/market_models.py`
- Create: `src/gmtrade_live/gateways/gm_history_market_gateway.py`
- Modify: `src/gmtrade_live/gateways/protocols.py`
- Create: `tests/unit/test_gm_history_market_gateway.py`

- [ ] **Step 1: 写失败测试，锁定“交易日历 + 指定交易日全市场快照”的协议**

```python
# tests/unit/test_gm_history_market_gateway.py
from datetime import date
from decimal import Decimal

from gmtrade_live.gateways.gm_history_market_gateway import GMHistoryMarketGateway


class FakeHistoryApi:
    def __init__(self) -> None:
        self.token = None

    def set_token(self, token: str) -> None:
        self.token = token

    def get_trading_dates(self, *args, **kwargs):
        return ["2026-04-10", "2026-04-14"]

    def get_symbols(self, *args, **kwargs):
        return [
            {
                "symbol": "SHSE.600000",
                "sec_name": "浦发银行",
                "open": 10.0,
                "high": 10.5,
                "low": 9.8,
                "close": 10.3,
                "pre_close": 9.9,
                "volume": 100000,
                "amount": 1030000,
                "turn_rate": 12.5,
                "is_suspended": False,
                "is_st": False,
                "upper_limit": 10.89,
                "lower_limit": 8.91,
                "listed_date": "1999-11-10",
            }
        ]


def test_history_gateway_reads_trading_dates() -> None:
    gateway = GMHistoryMarketGateway(api_module=FakeHistoryApi())
    gateway.connect("demo-token")
    dates = gateway.get_trading_dates(start_date=date(2026, 4, 10), end_date=date(2026, 4, 14))
    assert [item.isoformat() for item in dates] == ["2026-04-10", "2026-04-14"]


def test_history_gateway_reads_daily_snapshots() -> None:
    gateway = GMHistoryMarketGateway(api_module=FakeHistoryApi())
    gateway.connect("demo-token")
    rows = gateway.get_daily_snapshots(trade_date=date(2026, 4, 14))
    assert len(rows) == 1
    assert rows[0].symbol == "SHSE.600000"
    assert rows[0].close == Decimal("10.300")
    assert rows[0].turnover_rate == Decimal("12.500")
    assert rows[0].upper_limit_price == Decimal("10.890")
```

- [ ] **Step 2: 运行网关测试，确认当前仓库缺少历史市场数据入口**

Run: `conda run -n stock_analysis pytest tests/unit/test_gm_history_market_gateway.py -q`
Expected: FAIL，至少出现 `ModuleNotFoundError` 或 `GMHistoryMarketGateway` 未定义。

- [ ] **Step 3: 增加历史市场网关协议、市场链路 dataclass 和官方网关实现**

```python
# src/gmtrade_live/market_models.py
@dataclass(frozen=True, slots=True)
class MarketDailySnapshot:
    symbol: str
    name: str
    board: str
    trade_date: date
    listed_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    pre_close: Decimal
    volume: int
    amount: Decimal
    turnover_rate: Decimal
    is_st: bool
    suspended: bool
    has_trade: bool
    upper_limit_price: Decimal
    lower_limit_price: Decimal
```

```python
# src/gmtrade_live/gateways/protocols.py
class HistoricalMarketGateway(Protocol):
    def connect(self, token: str) -> None:
        pass
    def get_trading_dates(self, *, start_date: date, end_date: date) -> list[date]:
        pass
    def get_daily_snapshots(self, *, trade_date: date) -> list[MarketDailySnapshot]:
        pass
```

```python
# src/gmtrade_live/gateways/gm_history_market_gateway.py
class GMHistoryMarketGateway:
    def connect(self, token: str) -> None:
        self._api.set_token(token)

    def get_trading_dates(self, *, start_date: date, end_date: date) -> list[date]:
        rows = self._api.get_trading_dates(start_date=start_date, end_date=end_date)
        return [date.fromisoformat(str(item)) for item in rows]

    def get_daily_snapshots(self, *, trade_date: date) -> list[MarketDailySnapshot]:
        rows = self._api.get_symbols(trade_date=trade_date)
        return [_normalize_snapshot(row=row, trade_date=trade_date) for row in rows]
```

- [ ] **Step 4: 运行网关测试，确认读取结果已标准化为内部模型**

Run: `conda run -n stock_analysis pytest tests/unit/test_gm_history_market_gateway.py -q`
Expected: PASS，`MarketDailySnapshot` 字段标准化通过。

- [ ] **Step 5: 提交市场网关和模型脚手架**

```bash
git add src/gmtrade_live/market_models.py src/gmtrade_live/gateways/protocols.py src/gmtrade_live/gateways/gm_history_market_gateway.py tests/unit/test_gm_history_market_gateway.py
git commit -m "feat(market): add historical daily snapshot gateway"
```

### Task 3: 实现 MySQL 仓储与日线补数服务

**Files:**
- Create: `src/gmtrade_live/repositories/__init__.py`
- Create: `src/gmtrade_live/repositories/mysql_market_repository.py`
- Create: `src/gmtrade_live/services/market_data_sync_service.py`
- Create: `tests/unit/test_mysql_market_repository.py`
- Create: `tests/unit/test_market_data_sync_service.py`

- [ ] **Step 1: 写失败测试，锁定 schema、checkpoint 与缺口补数语义**

```python
# tests/unit/test_market_data_sync_service.py
from datetime import date

from gmtrade_live.market_models import MarketSyncResult
from gmtrade_live.services.market_data_sync_service import MarketDataSyncService


class FakeGateway:
    def __init__(self) -> None:
        self.requested_dates: list[date] = []

    def get_trading_dates(self, *, start_date: date, end_date: date) -> list[date]:
        return [date(2026, 4, 10), date(2026, 4, 11), date(2026, 4, 14)]

    def get_daily_snapshots(self, *, trade_date: date):
        self.requested_dates.append(trade_date)
        return []


class FakeRepository:
    def __init__(self) -> None:
        self.last_success_trade_date: date | None = date(2026, 4, 10)
        self.saved_trade_dates: list[date] = []

    def ensure_schema(self) -> None:
        return None

    def get_last_success_trade_date(self, job_name: str) -> date | None:
        return self.last_success_trade_date

    def upsert_daily_snapshots(self, snapshots) -> tuple[int, int]:
        return (0, 0)

    def save_last_success_trade_date(self, job_name: str, trade_date: date) -> None:
        self.saved_trade_dates.append(trade_date)


def test_market_data_sync_service_backfills_missing_trade_dates() -> None:
    service = MarketDataSyncService(gateway=FakeGateway(), repository=FakeRepository())
    result = service.sync()

    assert isinstance(result, MarketSyncResult)
    assert result.latest_trade_date.isoformat() == "2026-04-14"
    assert result.synced_trade_dates == 2
```

```python
# tests/unit/test_mysql_market_repository.py
def test_mysql_repository_uses_upsert_for_daily_snapshots() -> None:
    cursor = RecordingCursor()
    connection = RecordingConnection(cursor)
    repository = MySQLMarketRepository(connection_factory=lambda: connection)

    repository.upsert_daily_snapshots([build_snapshot()])

    assert "ON DUPLICATE KEY UPDATE" in cursor.executed_many_sql
    assert "market_daily_bar" in cursor.executed_many_sql


def test_mysql_repository_persists_checkpoint_by_job_name() -> None:
    cursor = RecordingCursor(fetchone_result=("2026-04-14",))
    connection = RecordingConnection(cursor)
    repository = MySQLMarketRepository(connection_factory=lambda: connection)

    trade_date = repository.get_last_success_trade_date("market_daily_sync")

    assert trade_date.isoformat() == "2026-04-14"
```

- [ ] **Step 2: 运行仓储与补数测试，确认当前仓库无 MySQL 事实源**

Run: `conda run -n stock_analysis pytest tests/unit/test_mysql_market_repository.py tests/unit/test_market_data_sync_service.py -q`
Expected: FAIL，至少出现 `ModuleNotFoundError` 或 `MySQLMarketRepository` / `MarketDataSyncService` 未定义。

- [ ] **Step 3: 实现 schema、upsert、checkpoint 和“三年全量 + 缺口补数”逻辑**

```python
# src/gmtrade_live/repositories/mysql_market_repository.py
class MySQLMarketRepository:
    def __init__(self, connection_factory: Callable[[], Connection]) -> None:
        self._connection_factory = connection_factory

    def ensure_schema(self) -> None:
        ddl = [
            """
            CREATE TABLE IF NOT EXISTS market_security_master (
                symbol VARCHAR(32) PRIMARY KEY,
                exchange VARCHAR(16) NOT NULL,
                name VARCHAR(128) NOT NULL,
                board VARCHAR(32) NOT NULL,
                listed_date DATE NOT NULL,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS market_daily_bar (
                symbol VARCHAR(32) NOT NULL,
                trade_date DATE NOT NULL,
                name VARCHAR(128) NOT NULL,
                board VARCHAR(32) NOT NULL,
                listed_date DATE NOT NULL,
                open DECIMAL(18, 6) NOT NULL,
                high DECIMAL(18, 6) NOT NULL,
                low DECIMAL(18, 6) NOT NULL,
                close DECIMAL(18, 6) NOT NULL,
                pre_close DECIMAL(18, 6) NOT NULL,
                volume BIGINT NOT NULL,
                amount DECIMAL(24, 6) NOT NULL,
                turnover_rate DECIMAL(18, 6) NOT NULL,
                is_st BOOLEAN NOT NULL,
                suspended BOOLEAN NOT NULL,
                has_trade BOOLEAN NOT NULL,
                upper_limit_price DECIMAL(18, 6) NOT NULL,
                lower_limit_price DECIMAL(18, 6) NOT NULL,
                PRIMARY KEY (symbol, trade_date)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS market_sync_checkpoint (
                job_name VARCHAR(64) PRIMARY KEY,
                last_success_trade_date DATE NOT NULL,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
            """,
        ]
        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                for sql in ddl:
                    cursor.execute(sql)
            connection.commit()

    def upsert_daily_snapshots(self, snapshots: Sequence[MarketDailySnapshot]) -> tuple[int, int]:
        # 为什么用 upsert：重复补数和断档补数必须可重入，不能依赖“只写一次”假设。
        sql = """
        INSERT INTO market_daily_bar (
            symbol, trade_date, name, board, listed_date, open, high, low, close,
            pre_close, volume, amount, turnover_rate, is_st, suspended, has_trade,
            upper_limit_price, lower_limit_price
        ) VALUES (
            %(symbol)s, %(trade_date)s, %(name)s, %(board)s, %(listed_date)s, %(open)s, %(high)s, %(low)s, %(close)s,
            %(pre_close)s, %(volume)s, %(amount)s, %(turnover_rate)s, %(is_st)s, %(suspended)s, %(has_trade)s,
            %(upper_limit_price)s, %(lower_limit_price)s
        )
        ON DUPLICATE KEY UPDATE
            name = VALUES(name),
            board = VALUES(board),
            listed_date = VALUES(listed_date),
            open = VALUES(open),
            high = VALUES(high),
            low = VALUES(low),
            close = VALUES(close),
            pre_close = VALUES(pre_close),
            volume = VALUES(volume),
            amount = VALUES(amount),
            turnover_rate = VALUES(turnover_rate),
            is_st = VALUES(is_st),
            suspended = VALUES(suspended),
            has_trade = VALUES(has_trade),
            upper_limit_price = VALUES(upper_limit_price),
            lower_limit_price = VALUES(lower_limit_price)
        """
        payloads = [
            {
                "symbol": item.symbol,
                "trade_date": item.trade_date,
                "name": item.name,
                "board": item.board,
                "listed_date": item.listed_date,
                "open": str(item.open),
                "high": str(item.high),
                "low": str(item.low),
                "close": str(item.close),
                "pre_close": str(item.pre_close),
                "volume": item.volume,
                "amount": str(item.amount),
                "turnover_rate": str(item.turnover_rate),
                "is_st": item.is_st,
                "suspended": item.suspended,
                "has_trade": item.has_trade,
                "upper_limit_price": str(item.upper_limit_price),
                "lower_limit_price": str(item.lower_limit_price),
            }
            for item in snapshots
        ]
        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.executemany(sql, payloads)
            connection.commit()
        return (len(payloads), 0)
```

```python
# src/gmtrade_live/services/market_data_sync_service.py
class MarketDataSyncService:
    def __init__(self, gateway: HistoricalMarketGateway, repository: MySQLMarketRepository) -> None:
        self._gateway = gateway
        self._repository = repository

    def sync(self) -> MarketSyncResult:
        self._repository.ensure_schema()
        last_success_trade_date = self._repository.get_last_success_trade_date("market_daily_sync")
        if last_success_trade_date is None:
            start_date = date.today().replace(year=date.today().year - 3)
        else:
            start_date = last_success_trade_date

        trade_dates = self._gateway.get_trading_dates(start_date=start_date, end_date=date.today())
        pending_trade_dates = [
            item
            for item in trade_dates
            if last_success_trade_date is None or item > last_success_trade_date
        ]

        inserted_rows = 0
        updated_rows = 0
        for trade_date in pending_trade_dates:
            snapshots = self._gateway.get_daily_snapshots(trade_date=trade_date)
            inserted, updated = self._repository.upsert_daily_snapshots(snapshots)
            inserted_rows += inserted
            updated_rows += updated

        latest_trade_date = pending_trade_dates[-1] if pending_trade_dates else last_success_trade_date
        if latest_trade_date is not None:
            self._repository.save_last_success_trade_date("market_daily_sync", latest_trade_date)

        return MarketSyncResult(
            latest_trade_date=latest_trade_date,
            inserted_rows=inserted_rows,
            updated_rows=updated_rows,
            synced_trade_dates=len(pending_trade_dates),
        )
```

- [ ] **Step 4: 跑仓储与补数测试，确认 checkpoint 和缺口补数都可重入**

Run: `conda run -n stock_analysis pytest tests/unit/test_mysql_market_repository.py tests/unit/test_market_data_sync_service.py -q`
Expected: PASS，仓储 upsert、checkpoint 和缺口补数语义通过。

- [ ] **Step 5: 提交 MySQL 与补数服务**

```bash
git add src/gmtrade_live/repositories/__init__.py src/gmtrade_live/repositories/mysql_market_repository.py src/gmtrade_live/services/market_data_sync_service.py tests/unit/test_mysql_market_repository.py tests/unit/test_market_data_sync_service.py
git commit -m "feat(market): add mysql repository and daily sync service"
```

### Task 4: 实现四类 analyzer 和最近 10 个交易日日报构建

**Files:**
- Create: `src/gmtrade_live/services/market_breadth_analyzer.py`
- Create: `src/gmtrade_live/services/market_profit_effect_analyzer.py`
- Create: `src/gmtrade_live/services/market_tolerance_analyzer.py`
- Create: `src/gmtrade_live/services/market_emotion_analyzer.py`
- Create: `src/gmtrade_live/services/market_close_report_builder.py`
- Create: `tests/unit/test_market_breadth_analyzer.py`
- Create: `tests/unit/test_market_profit_effect_analyzer.py`
- Create: `tests/unit/test_market_tolerance_analyzer.py`
- Create: `tests/unit/test_market_emotion_analyzer.py`
- Create: `tests/unit/test_market_close_report_builder.py`

- [ ] **Step 1: 用最小样本先锁定关键口径，避免实现时把“真实涨停”和“9.5% 情绪统计”混掉**

```python
# tests/unit/test_market_breadth_analyzer.py
def test_market_breadth_counts_up_down_and_ratio() -> None:
    frame = pd.DataFrame(
        [
            {"symbol": "SHSE.600000", "trade_date": "2026-04-14", "close": 11, "pre_close": 10, "amount": 100, "is_st": False, "suspended": False, "has_trade": True},
            {"symbol": "SHSE.600001", "trade_date": "2026-04-14", "close": 9, "pre_close": 10, "amount": 200, "is_st": False, "suspended": False, "has_trade": True},
            {"symbol": "SHSE.600002", "trade_date": "2026-04-14", "close": 10, "pre_close": 10, "amount": 300, "is_st": False, "suspended": False, "has_trade": True},
        ]
    )

    metrics = MarketBreadthAnalyzer().calculate(frame=frame, trade_date="2026-04-14")

    assert metrics.up_count == 1
    assert metrics.down_count == 1
    assert metrics.up_ratio == Decimal("0.333333")
    assert metrics.amount == Decimal("600")
```

```python
# tests/unit/test_market_profit_effect_analyzer.py
def test_profit_effect_uses_true_limit_up_pool() -> None:
    frame = build_limit_up_frame()
    metrics = MarketProfitEffectAnalyzer().calculate(frame=frame, trade_date="2026-04-14")
    assert metrics.limit_up_premium == Decimal("0.020000")
```

```python
# tests/unit/test_market_tolerance_analyzer.py
def test_tolerance_uses_hot_stocks_from_previous_day() -> None:
    frame = build_hot_stock_frame()
    metrics = MarketToleranceAnalyzer().calculate(frame=frame, trade_date="2026-04-14")
    assert metrics.close_above_avg_price_ratio == Decimal("0.500000")
```

```python
# tests/unit/test_market_emotion_analyzer.py
def test_emotion_counts_pct_breakouts_without_reusing_true_limit_logic() -> None:
    frame = build_emotion_frame()
    metrics = MarketEmotionAnalyzer().calculate(frame=frame, trade_date="2026-04-14")
    assert metrics.up_breakout_count == 2
    assert metrics.down_breakout_count == 1
```

```python
# tests/unit/test_market_close_report_builder.py
def test_report_builder_outputs_latest_10_trade_days_in_order() -> None:
    builder = MarketCloseReportBuilder(
        breadth_analyzer=MarketBreadthAnalyzer(),
        profit_analyzer=MarketProfitEffectAnalyzer(),
        tolerance_analyzer=MarketToleranceAnalyzer(),
        emotion_analyzer=MarketEmotionAnalyzer(),
    )
    report = builder.build(frame=build_70_day_frame(), report_trade_date="2026-04-14", recent_trade_days=10)
    assert len(report.daily_rows) == 10
    assert report.daily_rows[-1].trade_date.isoformat() == "2026-04-14"
```

- [ ] **Step 2: 运行 analyzer 与日报测试，确认当前仓库不存在市场分析层**

Run: `conda run -n stock_analysis pytest tests/unit/test_market_breadth_analyzer.py tests/unit/test_market_profit_effect_analyzer.py tests/unit/test_market_tolerance_analyzer.py tests/unit/test_market_emotion_analyzer.py tests/unit/test_market_close_report_builder.py -q`
Expected: FAIL，新增 analyzer / builder 均未定义。

- [ ] **Step 3: 用 `pandas` 向量化实现四类 analyzer 和 10 日日报构建器**

```python
# src/gmtrade_live/services/market_breadth_analyzer.py
class MarketBreadthAnalyzer:
    def calculate(self, *, frame: pd.DataFrame, trade_date: str) -> MarketBreadthMetrics:
        daily = _filter_eligible(frame, trade_date)
        up_count = int((daily["close"] > daily["pre_close"]).sum())
        down_count = int((daily["close"] < daily["pre_close"]).sum())
        total_count = int(len(daily))
        up_ratio = (
            Decimal(str(up_count / total_count)).quantize(Decimal("0.000001"))
            if total_count
            else Decimal("0")
        )
        return MarketBreadthMetrics(
            up_count=up_count,
            down_count=down_count,
            up_ratio=up_ratio,
            amount=Decimal(str(daily["amount"].sum())),
            high_20_count=_count_breakouts(frame, trade_date, window=20, side="high"),
            low_20_count=_count_breakouts(frame, trade_date, window=20, side="low"),
            high_60_count=_count_breakouts(frame, trade_date, window=60, side="high"),
            low_60_count=_count_breakouts(frame, trade_date, window=60, side="low"),
        )
```

```python
# src/gmtrade_live/services/market_tolerance_analyzer.py
class MarketToleranceAnalyzer:
    def calculate(self, *, frame: pd.DataFrame, trade_date: str) -> ToleranceMetrics:
        current_day = _filter_eligible(frame, trade_date)
        hot_pool = _resolve_hot_pool(frame, trade_date)
        hot_today = current_day[current_day["symbol"].isin(hot_pool)]
        avg_price = hot_today["amount"] / hot_today["volume"]
        above_ratio = (hot_today["close"] > avg_price).mean() if not hot_today.empty else 0
        drawdown = ((hot_today["high"] - hot_today["close"]) / hot_today["high"]).median()
        return ToleranceMetrics(
            failed_limit_up_return=_calculate_failed_limit_return(frame, trade_date),
            close_above_avg_price_ratio=Decimal(str(above_ratio)).quantize(Decimal("0.000001")),
            intraday_drawdown_median=Decimal(str(drawdown)).quantize(Decimal("0.000001")),
        )
```

```python
# src/gmtrade_live/services/market_close_report_builder.py
class MarketCloseReportBuilder:
    def build(self, *, frame: pd.DataFrame, report_trade_date: str, recent_trade_days: int) -> MarketCloseReport:
        trade_dates = sorted(frame["trade_date"].drop_duplicates().tolist())[-recent_trade_days:]
        rows: list[MarketCloseDailyRow] = []
        for trade_date in trade_dates:
            breadth = self._breadth_analyzer.calculate(frame=frame, trade_date=trade_date)
            profit = self._profit_analyzer.calculate(frame=frame, trade_date=trade_date)
            tolerance = self._tolerance_analyzer.calculate(frame=frame, trade_date=trade_date)
            emotion = self._emotion_analyzer.calculate(frame=frame, trade_date=trade_date)
            rows.append(build_daily_row(trade_date, breadth, profit, tolerance, emotion))
        return MarketCloseReport(
            report_trade_date=date.fromisoformat(report_trade_date),
            summary=_build_summary(rows[-1]),
            daily_rows=tuple(rows),
        )
```

- [ ] **Step 4: 运行 analyzer 测试，确认口径与 spec 一致**

Run: `conda run -n stock_analysis pytest tests/unit/test_market_breadth_analyzer.py tests/unit/test_market_profit_effect_analyzer.py tests/unit/test_market_tolerance_analyzer.py tests/unit/test_market_emotion_analyzer.py tests/unit/test_market_close_report_builder.py -q`
Expected: PASS，尤其要确认：
- `上涨占比 = 上涨家数 / 所有家数`
- 热门股按前一交易日定义
- `涨幅突破9.5家数` 与真实涨停判断分离

- [ ] **Step 5: 提交 analyzer 与 10 日日报构建器**

```bash
git add src/gmtrade_live/services/market_breadth_analyzer.py src/gmtrade_live/services/market_profit_effect_analyzer.py src/gmtrade_live/services/market_tolerance_analyzer.py src/gmtrade_live/services/market_emotion_analyzer.py src/gmtrade_live/services/market_close_report_builder.py tests/unit/test_market_breadth_analyzer.py tests/unit/test_market_profit_effect_analyzer.py tests/unit/test_market_tolerance_analyzer.py tests/unit/test_market_emotion_analyzer.py tests/unit/test_market_close_report_builder.py
git commit -m "feat(market): add daily analyzers and close report builder"
```

### Task 5: 实现飞书通知与一次性盘后任务入口

**Files:**
- Create: `src/gmtrade_live/services/feishu_notification_service.py`
- Create: `src/gmtrade_live/services/market_close_job.py`
- Modify: `src/gmtrade_live/app_runner.py`
- Create: `tests/unit/test_feishu_notification_service.py`
- Create: `tests/unit/test_market_close_job.py`

- [ ] **Step 1: 写失败测试，锁定“先补数、再分析、最后发送”和“同一交易日不重复发”语义**

```python
# tests/unit/test_market_close_job.py
from datetime import date

from gmtrade_live.market_models import MarketCloseReport, MarketSyncResult
from gmtrade_live.services.market_close_job import MarketCloseJob


class FakeSyncService:
    def sync(self) -> MarketSyncResult:
        return MarketSyncResult(
            latest_trade_date=date(2026, 4, 14),
            inserted_rows=10,
            updated_rows=0,
            synced_trade_dates=1,
        )


class FakeRepository:
    def __init__(self) -> None:
        self.last_sent_trade_date = None

    def get_last_success_trade_date(self, job_name: str):
        return self.last_sent_trade_date

    def save_last_success_trade_date(self, job_name: str, trade_date: date) -> None:
        self.last_sent_trade_date = trade_date

    def load_analysis_frame(self, *, end_trade_date: date, lookback_trade_days: int):
        return build_analysis_frame()


class FakeNotifier:
    def __init__(self) -> None:
        self.sent_reports: list[MarketCloseReport] = []

    def send(self, report: MarketCloseReport) -> None:
        self.sent_reports.append(report)


def test_market_close_job_runs_sync_then_report_then_send() -> None:
    notifier = FakeNotifier()
    job = MarketCloseJob(
        sync_service=FakeSyncService(),
        repository=FakeRepository(),
        report_builder=build_report_builder(),
        notifier=notifier,
    )

    result = job.run_once()

    assert result.report_trade_date.isoformat() == "2026-04-14"
    assert len(notifier.sent_reports) == 1


def test_market_close_job_skips_duplicate_send_for_same_trade_date() -> None:
    repository = FakeRepository()
    repository.last_sent_trade_date = date(2026, 4, 14)
    notifier = FakeNotifier()
    job = MarketCloseJob(
        sync_service=FakeSyncService(),
        repository=repository,
        report_builder=build_report_builder(),
        notifier=notifier,
    )

    result = job.run_once()

    assert result.skipped is True
    assert len(notifier.sent_reports) == 0
```

```python
# tests/unit/test_feishu_notification_service.py
def test_feishu_notification_service_posts_markdown_card(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: dict[str, object] = {}

    def fake_post(url: str, json: dict[str, object], timeout: int):
        recorded["url"] = url
        recorded["json"] = json
        return FakeResponse(status_code=200)

    monkeypatch.setattr("gmtrade_live.services.feishu_notification_service.requests.post", fake_post)
    service = FeishuNotificationService(webhook="https://example.invalid/webhook")

    service.send(build_report())

    assert recorded["url"] == "https://example.invalid/webhook"
    assert "最近10个交易日" in str(recorded["json"])
```

- [ ] **Step 2: 运行盘后任务与飞书测试，确认当前仓库尚无通知链路**

Run: `conda run -n stock_analysis pytest tests/unit/test_feishu_notification_service.py tests/unit/test_market_close_job.py -q`
Expected: FAIL，至少出现服务未定义或 `run_market_close_once` 不存在。

- [ ] **Step 3: 实现飞书服务、一次性盘后任务与 app_runner 入口**

```python
# src/gmtrade_live/services/feishu_notification_service.py
class FeishuNotificationService:
    def __init__(self, webhook: str) -> None:
        self._webhook = webhook

    def send(self, report: MarketCloseReport) -> None:
        payload = {
            "msg_type": "interactive",
            "card": build_feishu_card(report),
        }
        response = requests.post(self._webhook, json=payload, timeout=10)
        if response.status_code >= 400:
            raise ServiceError(
                code="feishu.send_failed",
                message="飞书推送失败",
                retryable=True,
                context={"status_code": str(response.status_code)},
            )
```

```python
# src/gmtrade_live/services/market_close_job.py
class MarketCloseJob:
    def __init__(
        self,
        sync_service: MarketDataSyncService,
        repository: MySQLMarketRepository,
        report_builder: MarketCloseReportBuilder,
        notifier: FeishuNotificationService,
    ) -> None:
        self._sync_service = sync_service
        self._repository = repository
        self._report_builder = report_builder
        self._notifier = notifier

    def run_once(self) -> MarketCloseJobResult:
        sync_result = self._sync_service.sync()
        last_sent_trade_date = self._repository.get_last_success_trade_date("market_close_report_sent")
        if last_sent_trade_date == sync_result.latest_trade_date:
            return MarketCloseJobResult(report_trade_date=sync_result.latest_trade_date, skipped=True)

        frame = self._repository.load_analysis_frame(
            end_trade_date=sync_result.latest_trade_date,
            lookback_trade_days=70,
        )
        report = self._report_builder.build(
            frame=frame,
            report_trade_date=sync_result.latest_trade_date.isoformat(),
            recent_trade_days=10,
        )
        self._notifier.send(report)
        self._repository.save_last_success_trade_date("market_close_report_sent", sync_result.latest_trade_date)
        return MarketCloseJobResult(report_trade_date=sync_result.latest_trade_date, skipped=False)
```

```python
# src/gmtrade_live/app_runner.py
def run_market_close_once(*, config_path: Path) -> int:
    runtime = load_runtime_config(config_path)
    logger = setup_logging("market-analysis", runtime.trade.log_dir)
    history_gateway = GMHistoryMarketGateway()
    history_gateway.connect(runtime.gm.token)
    repository = build_mysql_market_repository(runtime.mysql)
    sync_service = MarketDataSyncService(gateway=history_gateway, repository=repository)
    report_builder = build_market_close_report_builder()
    notifier = FeishuNotificationService(runtime.feishu.webhook)
    job = MarketCloseJob(
        sync_service=sync_service,
        repository=repository,
        report_builder=report_builder,
        notifier=notifier,
    )
    result = job.run_once()
    logger.info("market_close_completed trade_date=%s skipped=%s", result.report_trade_date, result.skipped)
    return 0
```

- [ ] **Step 4: 运行盘后任务与飞书测试**

Run: `conda run -n stock_analysis pytest tests/unit/test_feishu_notification_service.py tests/unit/test_market_close_job.py -q`
Expected: PASS，确认发送顺序正确且同一交易日不会重复发消息。

- [ ] **Step 5: 提交飞书通知与盘后任务入口**

```bash
git add src/gmtrade_live/services/feishu_notification_service.py src/gmtrade_live/services/market_close_job.py src/gmtrade_live/app_runner.py tests/unit/test_feishu_notification_service.py tests/unit/test_market_close_job.py
git commit -m "feat(market): add market close job and feishu notification"
```

### Task 6: 实现 `19:15` 调度入口与运行文档

**Files:**
- Create: `scheduler.py`
- Create: `src/gmtrade_live/runtime_scheduler.py`
- Create: `tests/unit/test_runtime_scheduler.py`
- Create: `docs/market-analysis-runtime.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: 写失败测试，锁定 scheduler 注册、手动触发和重试行为**

```python
# tests/unit/test_runtime_scheduler.py
def test_runtime_scheduler_registers_market_job_only() -> None:
    scheduler = RecordingScheduler()
    runtime = build_runtime_config(report_time="19:15", trade_enabled=False)

    runtime_scheduler = RuntimeScheduler(
        scheduler=scheduler,
        runtime_config=runtime,
        market_close_runner=lambda: 0,
    )
    runtime_scheduler.register_jobs()

    assert [job["id"] for job in scheduler.jobs] == ["market_analysis_job"]


def test_scheduler_entry_runs_market_close_now(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"value": False}

    def fake_run_market_close_once(*, config_path):
        called["value"] = True
        return 0

    monkeypatch.setitem(sys.modules, "gmtrade_live.app_runner", SimpleNamespace(run_market_close_once=fake_run_market_close_once))
    monkeypatch.setattr(sys, "argv", ["scheduler.py", "--config", "config/sim_account.yaml", "--run-market-close-now"])

    import scheduler

    assert scheduler.main() == 0
    assert called["value"] is True
```

- [ ] **Step 2: 运行 scheduler 测试，确认当前仓库还没有独立调度入口**

Run: `conda run -n stock_analysis pytest tests/unit/test_runtime_scheduler.py -q`
Expected: FAIL，至少出现 `ModuleNotFoundError: No module named 'scheduler'` 或 `RuntimeScheduler` 未定义。

- [ ] **Step 3: 实现 `19:15` 调度入口、固定 10 分钟重试和运行文档**

```python
# src/gmtrade_live/runtime_scheduler.py
class RuntimeScheduler:
    def __init__(
        self,
        scheduler: BlockingScheduler,
        runtime_config: RuntimeConfig,
        market_close_runner: Callable[[], int],
        logger: logging.Logger,
    ) -> None:
        self._scheduler = scheduler
        self._runtime_config = runtime_config
        self._market_close_runner = market_close_runner
        self._logger = logger

    def register_jobs(self) -> None:
        if self._runtime_config.trade.enabled:
            self._logger.warning("trade_job_enabled_but_not_implemented_yet")

        self._scheduler.add_job(
            self._run_market_close_with_retry,
            trigger=CronTrigger(day_of_week="mon-fri", hour=19, minute=15, timezone=self._runtime_config.gm.timezone),
            id="market_analysis_job",
            replace_existing=True,
        )

    def _run_market_close_with_retry(self) -> None:
        last_error: Exception | None = None
        for attempt in range(1, self._runtime_config.scheduler.max_attempts + 1):
            try:
                self._market_close_runner()
                return
            except Exception as exc:
                last_error = exc
                self._logger.error("market_analysis_retry_failed attempt=%s error=%s", attempt, exc, exc_info=True)
                if attempt >= self._runtime_config.scheduler.max_attempts:
                    break
                time.sleep(self._runtime_config.scheduler.retry_interval_minutes * 60)
        if last_error is not None:
            raise last_error
```

```python
# scheduler.py
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GMTrade market analysis scheduler")
    parser.add_argument("--config", required=True)
    parser.add_argument("--run-market-close-now", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    _ensure_local_src_on_path()
    from gmtrade_live.app_runner import run_market_close_once

    if args.run_market_close_now:
        return run_market_close_once(config_path=Path(args.config))

    from gmtrade_live.runtime_scheduler import build_and_start_runtime_scheduler
    build_and_start_runtime_scheduler(config_path=Path(args.config))
    return 0
```

```markdown
# docs/market-analysis-runtime.md
- 自动交易入口：`conda run -n stock_analysis python main.py --config config/sim_account.yaml --once`
- 盘后分析手动执行：`conda run -n stock_analysis python scheduler.py --config config/sim_account.yaml --run-market-close-now`
- 盘后分析常驻调度：`conda run -n stock_analysis python scheduler.py --config config/sim_account.yaml`
- 默认盘后调度时间：交易日 `19:15`
- 失败重试：每 `10` 分钟一次，最多 `3` 次
```

- [ ] **Step 4: 运行 scheduler 测试和一次全集成单测回归**

Run: `conda run -n stock_analysis pytest tests/unit/test_runtime_scheduler.py tests/unit/test_config.py tests/unit/test_gm_history_market_gateway.py tests/unit/test_mysql_market_repository.py tests/unit/test_market_data_sync_service.py tests/unit/test_market_breadth_analyzer.py tests/unit/test_market_profit_effect_analyzer.py tests/unit/test_market_tolerance_analyzer.py tests/unit/test_market_emotion_analyzer.py tests/unit/test_market_close_report_builder.py tests/unit/test_feishu_notification_service.py tests/unit/test_market_close_job.py -q`
Expected: PASS，确认配置、补数、分析、飞书、scheduler 全部联通。

Run: `conda run -n stock_analysis ruff check .`
Expected: `All checks passed!`

- [ ] **Step 5: 提交 scheduler 入口与文档**

```bash
git add scheduler.py src/gmtrade_live/runtime_scheduler.py tests/unit/test_runtime_scheduler.py docs/market-analysis-runtime.md AGENTS.md
git commit -m "feat(runtime): add nightly market analysis scheduler"
```

## Self-Review Checklist

- [ ] `19:15` 调度时间已在计划、示例配置和运行文档中保持一致，没有残留 `15:15`
- [ ] 计划没有把“交易启停策略”偷偷扩成当前实现范围，只保留 `trade.enabled` 扩展点
- [ ] 所有指标口径都遵守 spec：排除 `ST`、停牌、无成交；热门股按前一交易日定义；`上涨占比 = 上涨家数 / 所有家数`
- [ ] `market_sync_checkpoint` 同时复用为 `market_daily_sync` 和 `market_close_report_sent` 两类 checkpoint，没有重复建无意义结果表
- [ ] 所有测试命令都使用完整前缀，例如 `conda run -n stock_analysis pytest tests/unit/test_config.py -q` 或 `conda run -n stock_analysis ruff check .`
