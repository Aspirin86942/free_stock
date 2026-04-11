# M1 双向手工验证层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把当前 M1 从“手工卖单验证”升级为“支持 `buy/sell` 的双向手工验证层”，同时保持自动执行主线仍然只做自动卖出。

**Architecture:** 继续复用现有查询驱动主路径：`submit_order -> query_order_status -> query_execution_reports -> 内部事件 -> 聚合报告`。`buy` 与 `sell` 只在 CLI 参数、下单映射、日志与报告字段上分叉，不新增第二套服务，不扩展自动买入主线。

**Tech Stack:** Python 3.10+, `argparse`, `decimal.Decimal`, `gm.api`, `gm.enum`, `pytest`, stdlib `logging/json/pathlib`

---

## Planned File Structure

- Modify: `main.py` - 给 `m1` 增加 `--side buy|sell` 参数，并把方向传给 bootstrap。
- Modify: `src/gmtrade_live/bootstrap.py` - 接收 `side`，传给服务，并在 CLI JSON 中输出方向。
- Modify: `src/gmtrade_live/models.py` - 把 `TradeReport` 扩展为包含 `side`，并把 `OrderRequest` 的注释从“卖单”收敛为“交易请求”。
- Modify: `src/gmtrade_live/gateways/gmtrade_trade_gateway.py` - 让 `submit_order()` 支持 `buy/sell` 双向映射。
- Modify: `src/gmtrade_live/services/m1_manual_trade.py` - 让服务显式接收 `side`，做参数校验，并把方向写入日志和报告。
- Modify: `tests/unit/test_main.py` - 覆盖 `--side` 解析、校验和 main 分发。
- Modify: `tests/unit/test_bootstrap.py` - 覆盖 bootstrap 对 `side` 的传递与 JSON 输出。
- Modify: `tests/unit/test_models.py` - 覆盖 `OrderRequest` 的 `buy` 场景和 `TradeReport.side`。
- Modify: `tests/unit/test_official_gateways.py` - 覆盖 gateway 的 `buy/sell` 下单映射。
- Modify: `tests/unit/test_m1_manual_trade.py` - 覆盖服务层 `buy/sell` 双向查询驱动闭环。
- Modify: `tests/integration/test_m1_manual_trade_service.py` - 覆盖假 SDK 下 `buy` 集成闭环。
- Modify: `AGENTS.md` - 更新 M1 命令示例，显式展示 `--side sell` 与 `--side buy`。
- Modify: `docs/Proposal/量化交易系统规划书.md` - 明确 M1 是双向手工验证层，自动主线仍只做卖出。
- Modify: `docs/superpowers/specs/2026-04-08-m1-manual-trade-design.md` - 将历史 M1 设计改到双向手工验证口径。
- Modify: `docs/superpowers/plans/2026-04-08-m1-manual-trade.md` - 将历史 M1 实施计划改到双向手工验证口径。

## Scope Guard

本计划只交付以下内容：

- `m1` 命令支持 `--side buy|sell`
- 查询驱动的双向手工验证闭环
- `TradeReport` 和 CLI 输出带 `side`
- 文档与测试同步

本计划明确不交付以下内容：

- 自动买入策略
- 自动买入主线
- 扫描全市场寻找买点
- 买入后的仓位管理和风控扩展
- 数据库状态表
- 第二期状态机持久化

### Task 1: 扩展 CLI 与 Bootstrap 表面契约

**Files:**
- Modify: `tests/unit/test_main.py`
- Modify: `tests/unit/test_bootstrap.py`
- Modify: `main.py`
- Modify: `src/gmtrade_live/bootstrap.py`

- [ ] **Step 1: 先写 CLI 与 bootstrap 的失败测试**

在 `tests/unit/test_main.py` 追加：

```python
def test_parse_cli_args_accepts_m1_buy_market_order() -> None:
    args = main.parse_cli_args(
        [
            "--config",
            "config/sim_account.yaml",
            "--mode",
            "m1",
            "--side",
            "buy",
            "--symbol",
            "SHSE.600036",
            "--volume",
            "100",
            "--price-type",
            "market",
        ]
    )

    assert args.mode == "m1"
    assert args.side == "buy"
    assert args.symbol == "SHSE.600036"


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
            ]
        )
```

把 `tests/unit/test_main.py::test_main_dispatches_to_m1` 的 `sys.argv` 改成：

```python
[
    "main.py",
    "--config",
    "config/sim_account.yaml",
    "--mode",
    "m1",
    "--side",
    "sell",
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
]
```

并追加断言：

```python
assert captured["side"] == "sell"
```

把 `tests/unit/test_bootstrap.py::test_run_m1_manual_trade_prints_verification_passed` 中的假报告改成：

```python
report = SimpleNamespace(
    verification_passed=True,
    side="sell",
    cl_ord_id="ORDER_1",
    broker_order_id="BROKER_1",
    submit_accepted=True,
    order_status_confirmed=True,
    execution_status_confirmed=True,
    last_order_status="filled",
    rejection_reason=None,
    filled_volume=100,
    avg_price=Decimal("10.450"),
    message="交易状态已确认",
)
```

并把 payload 断言改成：

```python
assert set(payload) == {
    "verification_passed",
    "side",
    "cl_ord_id",
    "broker_order_id",
    "submit_accepted",
    "order_status_confirmed",
    "execution_status_confirmed",
    "last_order_status",
    "rejection_reason",
    "filled_volume",
    "avg_price",
    "message",
}
assert payload["side"] == "sell"
```

- [ ] **Step 2: 运行测试，确认当前实现还不支持 `side`**

Run:

```powershell
conda run -n stock_analysis pytest tests/unit/test_main.py tests/unit/test_bootstrap.py -q
```

Expected: FAIL。典型失败应包括：

- `argparse` 报 `unrecognized arguments: --side buy`
- `test_parse_cli_args_requires_side_for_m1` 显示 `Failed: DID NOT RAISE`
- `test_main_dispatches_to_m1` 或 bootstrap 输出断言中缺少 `side`

- [ ] **Step 3: 用最小代码把 CLI 和 bootstrap 契约补齐**

在 `main.py` 中把 parser 和 `parse_cli_args()` 改成：

```python
def build_parser() -> argparse.ArgumentParser:
    """构建项目统一 CLI 参数。"""
    parser = argparse.ArgumentParser(description="GMTrade connectivity and M1 manual trade")
    parser.add_argument("--config", required=True, help="Path to YAML config file")
    parser.add_argument("--mode", choices=("m0", "m1"), default="m0")
    parser.add_argument("--side", choices=("buy", "sell"))
    parser.add_argument("--symbol")
    parser.add_argument("--volume", type=_parse_positive_int)
    parser.add_argument("--price-type", choices=("market", "limit"))
    parser.add_argument("--price", type=_parse_positive_decimal)
    parser.add_argument("--timeout-seconds", type=_parse_positive_int, default=60)
    return parser


def parse_cli_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """解析并校验 M0/M1 模式所需参数。"""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.mode == "m1":
        if not args.side:
            parser.error("--mode m1 时必须提供 --side")
        if not args.symbol:
            parser.error("--mode m1 时必须提供 --symbol")
        if args.volume is None:
            parser.error("--mode m1 时必须提供 --volume")
        if not args.price_type:
            parser.error("--mode m1 时必须提供 --price-type")
        if args.price_type == "limit" and args.price is None:
            parser.error("--price-type limit 时必须提供 --price")
        if args.price_type == "market" and args.price is not None:
            parser.error("--price-type market 时不能提供 --price")

    return args
```

并把 `main.main()` 里对 bootstrap 的调用改成：

```python
if args.mode == "m1":
    return run_m1_manual_trade(
        config_path=config_path,
        side=args.side,
        symbol=args.symbol,
        volume=args.volume,
        price_type=args.price_type,
        price=args.price,
        timeout_seconds=args.timeout_seconds,
    )
```

在 `src/gmtrade_live/bootstrap.py` 中把函数签名和 JSON 输出改成：

```python
def run_m1_manual_trade(
    *,
    config_path: Path,
    side: str,
    symbol: str,
    volume: int,
    price_type: str,
    price: Decimal | None,
    timeout_seconds: int,
) -> int:
    """执行 M1 手工交易验证并输出最终交易报告。"""
    config = load_config(config_path)
    logger = setup_logging(config.strategy_name, config.log_dir)
    gateway = GMTradeGateway(account_id=config.account_id)

    gateway.connect(config)

    service = ManualTradeService(
        trade_gateway=gateway,
        logger=logger,
    )
    report = service.run(
        config=config,
        side=side,
        symbol=symbol,
        volume=volume,
        price_type=price_type,
        price=price,
        timeout_seconds=timeout_seconds,
    )

    print(
        json.dumps(
            {
                "verification_passed": report.verification_passed,
                "side": report.side,
                "cl_ord_id": report.cl_ord_id,
                "broker_order_id": report.broker_order_id,
                "submit_accepted": report.submit_accepted,
                "order_status_confirmed": report.order_status_confirmed,
                "execution_status_confirmed": report.execution_status_confirmed,
                "last_order_status": report.last_order_status,
                "rejection_reason": report.rejection_reason,
                "filled_volume": report.filled_volume,
                "avg_price": str(report.avg_price) if report.avg_price is not None else None,
                "message": report.message,
            },
            ensure_ascii=False,
        )
    )
    return 0 if report.verification_passed else 1
```

- [ ] **Step 4: 重新运行 CLI 与 bootstrap 测试**

Run:

```powershell
conda run -n stock_analysis pytest tests/unit/test_main.py tests/unit/test_bootstrap.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交这一批表面契约改动**

```powershell
git add main.py src/gmtrade_live/bootstrap.py tests/unit/test_main.py tests/unit/test_bootstrap.py
git commit -m "feat(m1): add side-aware cli and bootstrap"
```

### Task 2: 扩展模型契约到双向交易

**Files:**
- Modify: `tests/unit/test_models.py`
- Modify: `src/gmtrade_live/models.py`

- [ ] **Step 1: 先写模型失败测试**

在 `tests/unit/test_models.py` 追加：

```python
def test_order_request_buy_market_order() -> None:
    request = OrderRequest(
        symbol="SHSE.600036",
        volume=100,
        side="buy",
        price_type="market",
        price=None,
    )

    assert request.side == "buy"
    assert request.price_type == "market"


def test_trade_report_includes_side() -> None:
    report = TradeReport(
        account_id="demo-account",
        side="buy",
        symbol="SHSE.600036",
        requested_volume=100,
        price_type="market",
        submit_accepted=True,
        cl_ord_id="123456",
        broker_order_id="654321",
        order_status_confirmed=True,
        execution_status_confirmed=True,
        last_order_status="filled",
        rejection_reason=None,
        filled_volume=100,
        avg_price=Decimal("10.45"),
        verification_passed=True,
        message="交易状态已确认",
        started_at=_now(),
        finished_at=_now(),
    )

    assert report.side == "buy"
```

并把现有 `test_trade_report_success()` 与 `test_trade_report_timeout()` 里的 `TradeReport(...)` 构造都补上：

```python
side="sell",
```

- [ ] **Step 2: 运行模型测试，确认 `TradeReport` 还没有 `side`**

Run:

```powershell
conda run -n stock_analysis pytest tests/unit/test_models.py -q
```

Expected: FAIL with `TypeError: TradeReport.__init__() got an unexpected keyword argument 'side'`。

- [ ] **Step 3: 用最小实现补齐模型字段**

在 `src/gmtrade_live/models.py` 中把 `OrderRequest` 与 `TradeReport` 改成：

```python
@dataclass(frozen=True, slots=True)
class OrderRequest:
    """M1 手工交易请求。"""

    symbol: str
    volume: int
    side: str
    price_type: str
    price: Decimal | None
```

```python
@dataclass(frozen=True, slots=True)
class TradeReport:
    """M1 验证报告。"""

    account_id: str
    side: str
    symbol: str
    requested_volume: int
    price_type: str
    submit_accepted: bool
    cl_ord_id: str | None
    broker_order_id: str | None
    order_status_confirmed: bool
    execution_status_confirmed: bool
    last_order_status: str | None
    rejection_reason: str | None
    filled_volume: int
    avg_price: Decimal | None
    verification_passed: bool
    message: str
    started_at: datetime
    finished_at: datetime
```

- [ ] **Step 4: 重新运行模型测试**

Run:

```powershell
conda run -n stock_analysis pytest tests/unit/test_models.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交模型契约改动**

```powershell
git add src/gmtrade_live/models.py tests/unit/test_models.py
git commit -m "feat(m1): add side to trade report"
```

### Task 3: 让 Gateway 支持 `buy/sell` 双向下单映射

**Files:**
- Modify: `tests/unit/test_official_gateways.py`
- Modify: `src/gmtrade_live/gateways/gmtrade_trade_gateway.py`

- [ ] **Step 1: 先写 gateway 的失败测试**

在 `tests/unit/test_official_gateways.py` 顶部追加常量导入：

```python
from gm.enum import (
    OrderSide_Buy,
    OrderSide_Sell,
    PositionEffect_Close,
    PositionEffect_Open,
)
```

把现有卖出测试断言补强为：

```python
assert api.last_order_kwargs["side"] == OrderSide_Sell
assert api.last_order_kwargs["position_effect"] == PositionEffect_Close
```

再新增买入测试：

```python
def test_gm_api_gateway_submits_buy_order_via_query_driven_path() -> None:
    api = FakeGMApi()
    gateway = GMTradeGateway(api_module=api, account_id="demo-account")
    config = _build_config()

    gateway.connect(config)
    result = gateway.submit_order(
        OrderRequest(
            symbol="SHSE.600036",
            volume=100,
            side="buy",
            price_type="market",
            price=None,
        )
    )

    assert api.last_order_kwargs is not None
    assert api.last_order_kwargs["account"] == "demo-account"
    assert api.last_order_kwargs["side"] == OrderSide_Buy
    assert api.last_order_kwargs["position_effect"] == PositionEffect_Open
    assert result.accepted is True
    assert result.cl_ord_id == "ORDER_1"
```

- [ ] **Step 2: 运行 gateway 测试，确认当前实现仍拒绝 `buy`**

Run:

```powershell
conda run -n stock_analysis pytest tests/unit/test_official_gateways.py -q
```

Expected: FAIL。典型失败应为：

- `ServiceError(code='gmtrade.unsupported_side', message='M1 仅支持手动卖单验证')`
- 或买入断言拿不到预期的 `side` / `position_effect`

- [ ] **Step 3: 用最小实现支持双向映射**

在 `src/gmtrade_live/gateways/gmtrade_trade_gateway.py` 顶部补上买入常量：

```python
from gm.enum import (
    OrderSide_Buy,
    OrderSide_Sell,
    OrderType_Limit,
    OrderType_Market,
    PositionEffect_Close,
    PositionEffect_Open,
)
```

把 `submit_order()` 中的方向分支改成：

```python
submit_side, position_effect = _resolve_submit_side_and_effect(request.side)

raw_result = self._api.order_volume(
    symbol=request.symbol,
    volume=request.volume,
    side=submit_side,
    order_type=order_type,
    position_effect=position_effect,
    price=order_price,
    account=self._account_id,
)
```

并新增辅助函数：

```python
def _resolve_submit_side_and_effect(side: str) -> tuple[int, int]:
    """把内部买卖方向映射为掘金常量。"""
    if side == "sell":
        return OrderSide_Sell, PositionEffect_Close
    if side == "buy":
        return OrderSide_Buy, PositionEffect_Open
    raise ServiceError(
        code="gmtrade.invalid_side",
        message="side 仅支持 buy 或 sell",
        retryable=False,
        context={"side": side},
    )
```

同时删掉原先只允许 `sell` 的硬编码报错分支。

- [ ] **Step 4: 重新运行 gateway 测试**

Run:

```powershell
conda run -n stock_analysis pytest tests/unit/test_official_gateways.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交 gateway 双向映射改动**

```powershell
git add src/gmtrade_live/gateways/gmtrade_trade_gateway.py tests/unit/test_official_gateways.py
git commit -m "feat(m1): support buy and sell submit mapping"
```

### Task 4: 让 ManualTradeService 支持双向查询驱动闭环

**Files:**
- Modify: `tests/unit/test_m1_manual_trade.py`
- Modify: `tests/integration/test_m1_manual_trade_service.py`
- Modify: `src/gmtrade_live/services/m1_manual_trade.py`

- [ ] **Step 1: 先写服务层与集成层失败测试**

在 `tests/unit/test_m1_manual_trade.py` 里把所有 `service.run(...)` 调用都补上显式方向：

```python
side="sell",
```

然后新增买入成功场景：

```python
def test_manual_trade_service_confirms_buy_order_via_query() -> None:
    gateway = FakeTradeGateway(
        _accepted_result(),
        order_status_snapshots=(
            _order_status_snapshot(status="filled", filled_volume=100, remaining_volume=0),
        ),
        execution_snapshots=((_execution_snapshot(),),),
    )
    service = _build_service(gateway)

    report = service.run(
        config=_build_config(),
        side="buy",
        symbol="SHSE.600036",
        volume=100,
        price_type="market",
        price=None,
        timeout_seconds=2,
    )

    assert gateway.last_request is not None
    assert gateway.last_request.side == "buy"
    assert report.side == "buy"
    assert report.verification_passed is True
    assert report.message == "交易状态已确认"
```

在已有卖出成功场景里补强断言：

```python
assert report.side == "sell"
```

在 `tests/integration/test_m1_manual_trade_service.py` 追加：

```python
def test_m1_manual_trade_fake_sdk_buy_integration(monkeypatch) -> None:
    api = FakeGMApi()
    gateway = GMTradeGateway(api_module=api, account_id="demo-account")
    monkeypatch.setattr(
        gateway_module,
        "_fetch_execution_reports",
        lambda *, account_id, cl_ord_id: [
            {
                "cl_ord_id": cl_ord_id,
                "order_id": "BROKER_1",
                "symbol": "SHSE.600036",
                "volume": 100,
                "price": Decimal("10.45"),
                "created_at": datetime(
                    2026,
                    4,
                    9,
                    10,
                    30,
                    tzinfo=ZoneInfo("Asia/Shanghai"),
                ),
            }
        ],
    )
    service = ManualTradeService(
        trade_gateway=gateway,
        logger=logging.getLogger("test"),
    )
    config = _build_config()

    gateway.connect(config)
    report = service.run(
        config=config,
        side="buy",
        symbol="SHSE.600036",
        volume=100,
        price_type="market",
        price=None,
        timeout_seconds=2,
    )

    assert report.side == "buy"
    assert report.verification_passed is True
    assert report.execution_status_confirmed is True
```

- [ ] **Step 2: 运行服务层测试，确认当前 `run()` 还不接受 `side`**

Run:

```powershell
conda run -n stock_analysis pytest tests/unit/test_m1_manual_trade.py tests/integration/test_m1_manual_trade_service.py -q
```

Expected: FAIL with `TypeError: ManualTradeService.run() got an unexpected keyword argument 'side'`。

- [ ] **Step 3: 用最小实现让服务层传播 `side`**

在 `src/gmtrade_live/services/m1_manual_trade.py` 中把 `run()` 签名改成：

```python
def run(
    self,
    *,
    config: AppConfig,
    side: str,
    symbol: str,
    volume: int,
    price_type: str,
    price: Decimal | None,
    timeout_seconds: int,
) -> TradeReport:
```

把输入校验调用改成：

```python
self._validate_inputs(
    side=side,
    symbol=symbol,
    volume=volume,
    price_type=price_type,
    price=price,
    timeout_seconds=timeout_seconds,
)
```

把请求对象改成：

```python
request = OrderRequest(
    symbol=symbol,
    volume=volume,
    side=side,
    price_type=price_type,
    price=price,
)
```

把启动日志改成：

```python
self._logger.info(
    "m1_manual_trade_starting account_id=%s side=%s symbol=%s volume=%s price_type=%s timeout_seconds=%s",
    config.account_id,
    side,
    symbol,
    volume,
    price_type,
    timeout_seconds,
)
```

把提交请求日志改成：

```python
self._logger.info(
    "order_submit_request account_id=%s side=%s symbol=%s volume=%s price_type=%s",
    config.account_id,
    side,
    symbol,
    volume,
    price_type,
)
```

把 `_build_report()` 改成：

```python
return TradeReport(
    account_id=config.account_id,
    side=request.side,
    symbol=request.symbol,
    requested_volume=request.volume,
    price_type=request.price_type,
    submit_accepted=submit_result.accepted if submit_result is not None else False,
    cl_ord_id=submit_result.cl_ord_id if submit_result is not None else None,
    broker_order_id=collected.broker_order_id,
    order_status_confirmed=collected.order_status_confirmed,
    execution_status_confirmed=collected.execution_status_confirmed,
    last_order_status=collected.last_order_status,
    rejection_reason=collected.rejection_reason,
    filled_volume=collected.filled_volume,
    avg_price=collected.avg_price,
    verification_passed=verification_passed,
    message=message,
    started_at=started_at,
    finished_at=finished_at,
)
```

并把 `_validate_inputs()` 改成：

```python
def _validate_inputs(
    self,
    *,
    side: str,
    symbol: str,
    volume: int,
    price_type: str,
    price: Decimal | None,
    timeout_seconds: int,
) -> None:
    """校验 M1 请求参数，避免把非法请求送到柜台。"""
    if side not in {"buy", "sell"}:
        raise ServiceError(
            code="manual_trade.invalid_side",
            message="side 仅支持 buy 或 sell",
            retryable=False,
            context={"side": side},
        )
```

同时把文件头部和类注释从“手动卖单验证”收敛为“手工交易验证”。

- [ ] **Step 4: 重新运行服务层与集成层测试**

Run:

```powershell
conda run -n stock_analysis pytest tests/unit/test_m1_manual_trade.py tests/integration/test_m1_manual_trade_service.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交服务层双向闭环改动**

```powershell
git add src/gmtrade_live/services/m1_manual_trade.py tests/unit/test_m1_manual_trade.py tests/integration/test_m1_manual_trade_service.py
git commit -m "feat(m1): propagate side through manual trade service"
```

### Task 5: 同步文档与命令示例，并做全量验证

**Files:**
- Modify: `AGENTS.md`
- Modify: `docs/Proposal/量化交易系统规划书.md`
- Modify: `docs/superpowers/specs/2026-04-08-m1-manual-trade-design.md`
- Modify: `docs/superpowers/plans/2026-04-08-m1-manual-trade.md`

- [ ] **Step 1: 更新文档到双向手工验证口径**

把 `AGENTS.md` 的 M1 命令示例改成：

```bash
# M1 手动卖出验证
conda run -n stock_analysis python main.py --config config/sim_account.yaml --mode m1 \
  --side sell --symbol SHSE.600839 --volume 100 --price-type market --timeout-seconds 60

# M1 手动买入验证
conda run -n stock_analysis python main.py --config config/sim_account.yaml --mode m1 \
  --side buy --symbol SHSE.600839 --volume 100 --price-type limit --price 10.50 \
  --timeout-seconds 120
```

把 `docs/Proposal/量化交易系统规划书.md` 增加明确表述：

```markdown
- M1 为双向手工验证层，支持 `buy/sell` 两个方向
- 自动执行主线仍然只做自动卖出，不扩展自动买入
```

把 `docs/superpowers/specs/2026-04-08-m1-manual-trade-design.md` 的目标和范围改成：

```markdown
- 标题改为：`# M1 双向手工验证查询收口设计`
- M1 支持 `--side buy|sell`
- 主路径仍然是查询驱动
- 自动主线仍只做卖出
```

把 `docs/superpowers/plans/2026-04-08-m1-manual-trade.md` 的 Goal、Architecture、Acceptance 与命令示例改成：

```markdown
- 标题改为：`# M1 双向手工验证查询收口 Implementation Plan`
- `m1` 命令支持 `--side buy|sell`
- `buy` 和 `sell` 共用 `submit -> query_order_status -> query_execution_reports -> report`
```

- [ ] **Step 2: 用搜索验证目标文档已经不再停留在单向 M1 口径**

Run:

```powershell
rg -n "手动卖单验证|M1 手动卖单查询收口|--side buy|--side sell|双向手工验证层" AGENTS.md docs/Proposal/量化交易系统规划书.md docs/superpowers/specs/2026-04-08-m1-manual-trade-design.md docs/superpowers/plans/2026-04-08-m1-manual-trade.md -S
```

Expected:

- 可以看到 `--side buy`、`--side sell`、`双向手工验证层`
- 不应再在上述目标文件中看到“当前 M1 只验证卖单”的表述

- [ ] **Step 3: 运行本次改动的关键测试集合**

Run:

```powershell
conda run -n stock_analysis pytest tests/unit/test_main.py tests/unit/test_bootstrap.py tests/unit/test_models.py tests/unit/test_official_gateways.py tests/unit/test_m1_manual_trade.py tests/integration/test_m1_manual_trade_service.py -q
```

Expected: PASS。

- [ ] **Step 4: 运行全量测试，确认没有回归**

Run:

```powershell
conda run -n stock_analysis pytest -q
```

Expected: PASS。

- [ ] **Step 5: 提交文档同步与最终收口**

```powershell
git add AGENTS.md docs/Proposal/量化交易系统规划书.md docs/superpowers/specs/2026-04-08-m1-manual-trade-design.md docs/superpowers/plans/2026-04-08-m1-manual-trade.md
git commit -m "docs(m1): document bidirectional manual validation"
```
