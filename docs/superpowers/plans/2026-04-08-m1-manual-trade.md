# M1 手动卖单委托-回报链路 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 M1 里程碑 - 手动触发卖单、提交委托、接收回报（委托状态 + 成交）、输出验证报告的完整链路。

**Architecture:** 在 M0 基础上增加：(1) 回调处理器（转换 SDK 回报为内部事件并入队）；(2) 交易网关扩展（提交委托 + 注册回调）；(3) 手动验证服务（同步等待两类回报）；(4) CLI 扩展（支持 M1 模式）。单线程顺序处理模型：SDK 回调只做转换和入队，业务线程同步从 Queue 拉取事件。

**Tech Stack:** Python 3.10+, gm==3.0.183, PyYAML, pytest, stdlib logging/decimal/zoneinfo/queue（`threading` 仅用于测试桩模拟 SDK 异步回调）

---

## Planned File Structure

**New files:**
- `src/gmtrade_live/gateways/callback_handler.py` - 回调处理器（转换 + 入队）
- `src/gmtrade_live/services/m1_manual_trade.py` - 手动验证服务
- `tests/unit/test_models.py` - M1 模型单元测试
- `tests/unit/test_protocols.py` - 网关协议单元测试
- `tests/unit/test_callback_handler.py` - 回调处理器单元测试
- `tests/unit/test_m1_manual_trade.py` - 手动验证服务单元测试
- `tests/integration/test_m1_manual_trade_service.py` - M1 集成测试

**Modified files:**
- `src/gmtrade_live/models.py` - 增加 M1 相关模型
- `src/gmtrade_live/gateways/protocols.py` - 扩展 TradeGateway 协议
- `src/gmtrade_live/gateways/gmtrade_trade_gateway.py` - 增加委托能力
- `src/gmtrade_live/bootstrap.py` - 增加 run_m1_manual_trade()
- `main.py` - 增加 --mode 和 M1 参数
- `tests/unit/test_main.py` - 增加 M1 参数测试
- `tests/unit/test_official_gateways.py` - 更新 Gateway 测试
- `AGENTS.md` - 补充 M1 命令说明

## Scope Guard

M1 只做：手动触发卖单 → 提交委托 → 接收回报 → 验证报告。

M1 不做：自动卖出、止盈止损、卖出许可、防重复卖单、状态机收口、更新 PositionStateManager、成交后重查账户。

---

## Task 1: 扩展数据模型

**Files:**
- Modify: `src/gmtrade_live/models.py`
- Test: `tests/unit/test_models.py` (新建)

- [ ] **Step 1: 写 OrderRequest 模型的测试**

```python
# tests/unit/test_models.py
from decimal import Decimal
from gmtrade_live.models import OrderRequest

def test_order_request_market_order():
    """市价单请求"""
    req = OrderRequest(
        symbol="SHSE.600036",
        volume=100,
        side="sell",
        price_type="market",
        price=None,
    )
    assert req.symbol == "SHSE.600036"
    assert req.volume == 100
    assert req.side == "sell"
    assert req.price_type == "market"
    assert req.price is None

def test_order_request_limit_order():
    """限价单请求"""
    req = OrderRequest(
        symbol="SHSE.600036",
        volume=100,
        side="sell",
        price_type="limit",
        price=Decimal("10.50"),
    )
    assert req.price == Decimal("10.50")
```

- [ ] **Step 2: 运行测试验证失败**

Run: `conda run -n stock_analysis pytest tests/unit/test_models.py::test_order_request_market_order -v`
Expected: FAIL with "cannot import name 'OrderRequest'"

- [ ] **Step 3: 在 models.py 中添加 OrderRequest**

```python
# src/gmtrade_live/models.py (在文件末尾添加)

@dataclass(frozen=True, slots=True)
class OrderRequest:
    """卖单请求"""
    symbol: str              # 标的代码，如 "SHSE.600036"
    volume: int              # 卖出数量
    side: str                # 固定为 "sell"
    price_type: str          # "market" 或 "limit"
    price: Decimal | None    # 限价单时必填，市价单为 None
```

- [ ] **Step 4: 运行测试验证通过**

Run: `conda run -n stock_analysis pytest tests/unit/test_models.py::test_order_request_market_order -v`
Expected: PASS

- [ ] **Step 5: 写 OrderSubmitResult 模型的测试**

```python
# tests/unit/test_models.py (追加)
from datetime import datetime
from zoneinfo import ZoneInfo
from gmtrade_live.models import OrderSubmitResult

def test_order_submit_result_accepted():
    """委托提交成功"""
    now = datetime.now(tz=ZoneInfo("Asia/Shanghai"))
    result = OrderSubmitResult(
        accepted=True,
        order_id="123456",
        symbol="SHSE.600036",
        message="Order accepted",
        raw_status="0",
        event_time=now,
    )
    assert result.accepted is True
    assert result.order_id == "123456"
    assert result.raw_status == "0"

def test_order_submit_result_rejected():
    """委托提交被拒绝"""
    now = datetime.now(tz=ZoneInfo("Asia/Shanghai"))
    result = OrderSubmitResult(
        accepted=False,
        order_id=None,
        symbol="SHSE.600036",
        message="Insufficient balance",
        raw_status="1001",
        event_time=now,
    )
    assert result.accepted is False
    assert result.order_id is None
```

- [ ] **Step 6: 运行测试验证失败**

Run: `conda run -n stock_analysis pytest tests/unit/test_models.py::test_order_submit_result_accepted -v`
Expected: FAIL with "cannot import name 'OrderSubmitResult'"

- [ ] **Step 7: 在 models.py 中添加 OrderSubmitResult**

```python
# src/gmtrade_live/models.py (追加)

@dataclass(frozen=True, slots=True)
class OrderSubmitResult:
    """委托提交结果"""
    accepted: bool           # 是否被接受
    order_id: str | None     # 委托编号（被拒绝时为 None）
    symbol: str
    message: str             # 提交结果描述
    raw_status: str          # 原始状态码，用于审计
    event_time: datetime
```

- [ ] **Step 8: 运行测试验证通过**

Run: `conda run -n stock_analysis pytest tests/unit/test_models.py::test_order_submit_result_accepted -v`
Expected: PASS

- [ ] **Step 9: 写 OrderEvent 和 ExecutionEvent 模型的测试**

```python
# tests/unit/test_models.py (追加)
from gmtrade_live.models import OrderEvent, ExecutionEvent

def test_order_event():
    """委托状态回报"""
    now = datetime.now(tz=ZoneInfo("Asia/Shanghai"))
    event = OrderEvent(
        order_id="123456",
        symbol="SHSE.600036",
        status="filled",
        filled_volume=100,
        remaining_volume=0,
        event_time=now,
        message="Order filled",
    )
    assert event.order_id == "123456"
    assert event.status == "filled"
    assert event.filled_volume == 100

def test_execution_event():
    """成交回报"""
    now = datetime.now(tz=ZoneInfo("Asia/Shanghai"))
    event = ExecutionEvent(
        order_id="123456",
        symbol="SHSE.600036",
        filled_volume=100,
        avg_price=Decimal("10.45"),
        event_time=now,
    )
    assert event.filled_volume == 100
    assert event.avg_price == Decimal("10.45")
```

- [ ] **Step 10: 运行测试验证失败**

Run: `conda run -n stock_analysis pytest tests/unit/test_models.py::test_order_event -v`
Expected: FAIL with "cannot import name 'OrderEvent'"

- [ ] **Step 11: 在 models.py 中添加 OrderEvent 和 ExecutionEvent**

```python
# src/gmtrade_live/models.py (追加)

@dataclass(frozen=True, slots=True)
class OrderEvent:
    """委托状态回报"""
    order_id: str
    symbol: str
    status: str              # 如 "submitted", "filled", "rejected"
    filled_volume: int       # 已成交数量
    remaining_volume: int    # 剩余数量
    event_time: datetime
    message: str


@dataclass(frozen=True, slots=True)
class ExecutionEvent:
    """成交回报"""
    order_id: str
    symbol: str
    filled_volume: int       # 本次成交数量（单次回报）
    avg_price: Decimal       # 本次成交均价
    event_time: datetime
```

- [ ] **Step 12: 运行测试验证通过**

Run: `conda run -n stock_analysis pytest tests/unit/test_models.py -v`
Expected: ALL PASS

- [ ] **Step 13: 写 TradeReport 模型的测试**

```python
# tests/unit/test_models.py (追加)
from gmtrade_live.models import TradeReport

def test_trade_report_success():
    """验证成功报告"""
    now = datetime.now(tz=ZoneInfo("Asia/Shanghai"))
    report = TradeReport(
        account_id="test_account",
        symbol="SHSE.600036",
        requested_volume=100,
        price_type="market",
        submit_accepted=True,
        order_id="123456",
        order_event_received=True,
        execution_event_received=True,
        last_order_status="filled",
        filled_volume=100,
        avg_price=Decimal("10.45"),
        success=True,
        message="M1 verification completed successfully",
        started_at=now,
        finished_at=now,
    )
    assert report.success is True
    assert report.order_event_received is True
    assert report.execution_event_received is True

def test_trade_report_timeout():
    """验证超时报告"""
    now = datetime.now(tz=ZoneInfo("Asia/Shanghai"))
    report = TradeReport(
        account_id="test_account",
        symbol="SHSE.600036",
        requested_volume=100,
        price_type="market",
        submit_accepted=True,
        order_id="123456",
        order_event_received=True,
        execution_event_received=False,
        last_order_status="submitted",
        filled_volume=0,
        avg_price=None,
        success=False,
        message="missing_execution_event",
        started_at=now,
        finished_at=now,
    )
    assert report.success is False
    assert report.message == "missing_execution_event"
```

- [ ] **Step 14: 运行测试验证失败**

Run: `conda run -n stock_analysis pytest tests/unit/test_models.py::test_trade_report_success -v`
Expected: FAIL with "cannot import name 'TradeReport'"

- [ ] **Step 15: 在 models.py 中添加 TradeReport**

```python
# src/gmtrade_live/models.py (追加)

@dataclass(frozen=True, slots=True)
class TradeReport:
    """M1 验证报告"""
    account_id: str
    symbol: str
    requested_volume: int
    price_type: str
    submit_accepted: bool
    order_id: str | None
    order_event_received: bool      # 是否收到委托状态回报
    execution_event_received: bool  # 是否收到成交回报
    last_order_status: str | None
    filled_volume: int              # 累计成交量（本次验证期间）
    avg_price: Decimal | None       # 最后一次成交回报的均价
    success: bool                   # 两类回报都收到才为 True
    message: str
    started_at: datetime
    finished_at: datetime
```

- [ ] **Step 16: 运行所有模型测试验证通过**

Run: `conda run -n stock_analysis pytest tests/unit/test_models.py -v`
Expected: ALL PASS

- [ ] **Step 17: 提交**

```bash
git add src/gmtrade_live/models.py tests/unit/test_models.py
git commit -m "feat(m1): add order and trade report models

Add M1 data models:
- OrderRequest: sell order request
- OrderSubmitResult: order submission result
- OrderEvent: order status callback event
- ExecutionEvent: execution report event
- TradeReport: M1 verification report

All models use frozen=True, slots=True for immutability.
Amounts use Decimal, not float.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: 扩展网关协议

**Files:**
- Modify: `src/gmtrade_live/gateways/protocols.py`

- [ ] **Step 1: 写协议扩展的测试**

```python
# tests/unit/test_protocols.py (新建)
from typing import Protocol
from gmtrade_live.gateways.protocols import TradeGateway
from gmtrade_live.models import OrderRequest, OrderSubmitResult

def test_trade_gateway_protocol_has_submit_order():
    """验证 TradeGateway 协议包含 submit_order 方法"""
    # 这是一个类型检查测试，主要验证协议定义
    assert hasattr(TradeGateway, 'submit_order')
```

- [ ] **Step 2: 运行测试验证失败**

Run: `conda run -n stock_analysis pytest tests/unit/test_protocols.py -v`
Expected: FAIL with "TradeGateway has no attribute 'submit_order'"

- [ ] **Step 3: 在 protocols.py 中扩展 TradeGateway 协议**

```python
# src/gmtrade_live/gateways/protocols.py (修改现有 TradeGateway)
from typing import Protocol
from gmtrade_live.models import CashSnapshot, PositionSnapshot, OrderRequest, OrderSubmitResult

class TradeGateway(Protocol):
    """交易网关协议"""
    
    def get_cash(self, account_id: str) -> CashSnapshot:
        """获取账户资金"""
        ...
    
    def get_positions(self, account_id: str) -> list[PositionSnapshot]:
        """获取持仓列表"""
        ...
    
    def submit_order(self, request: OrderRequest) -> OrderSubmitResult:
        """提交卖单委托（account_id 从初始化配置中获取）"""
        ...
```

- [ ] **Step 4: 运行测试验证通过**

Run: `conda run -n stock_analysis pytest tests/unit/test_protocols.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/gmtrade_live/gateways/protocols.py tests/unit/test_protocols.py
git commit -m "feat(m1): extend TradeGateway protocol with submit_order

Add submit_order() method to TradeGateway protocol.
Method signature: submit_order(request: OrderRequest) -> OrderSubmitResult
account_id is obtained from gateway initialization, not passed per call.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: 实现回调处理器

**Files:**
- Create: `src/gmtrade_live/gateways/callback_handler.py`
- Test: `tests/unit/test_callback_handler.py`

- [ ] **Step 1: 写回调处理器入队测试**

```python
# tests/unit/test_callback_handler.py
import logging
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
from unittest.mock import Mock
from gmtrade_live.gateways.callback_handler import CallbackHandler
from gmtrade_live.models import OrderEvent, ExecutionEvent

def test_callback_handler_on_order_status():
    """测试委托状态回调入队"""
    logger = logging.getLogger("test")
    handler = CallbackHandler(logger)
    
    # 模拟 SDK 回调对象
    mock_order = Mock()
    mock_order.cl_ord_id = "123456"
    mock_order.symbol = "SHSE.600036"
    mock_order.status = 3  # 假设 3 表示 filled
    mock_order.filled_volume = 100
    mock_order.volume = 100
    mock_order.created_at = datetime.now(tz=ZoneInfo("Asia/Shanghai"))
    
    handler.on_order_status(mock_order)
    
    assert not handler.event_queue.empty()
    event = handler.event_queue.get()
    assert isinstance(event, OrderEvent)
    assert event.order_id == "123456"

def test_callback_handler_on_execution_report():
    """测试成交回报入队"""
    logger = logging.getLogger("test")
    handler = CallbackHandler(logger)
    
    # 模拟 SDK 回调对象
    mock_exec = Mock()
    mock_exec.cl_ord_id = "123456"
    mock_exec.symbol = "SHSE.600036"
    mock_exec.filled_volume = 100
    mock_exec.filled_vwap = 10.45
    mock_exec.created_at = datetime.now(tz=ZoneInfo("Asia/Shanghai"))
    
    handler.on_execution_report(mock_exec)
    
    assert not handler.event_queue.empty()
    event = handler.event_queue.get()
    assert isinstance(event, ExecutionEvent)
    assert event.filled_volume == 100
    assert event.avg_price == Decimal("10.45")

def test_callback_handler_clear_queue():
    """测试清空队列"""
    logger = logging.getLogger("test")
    handler = CallbackHandler(logger)
    
    # 放入一些事件
    handler.event_queue.put(Mock())
    handler.event_queue.put(Mock())
    assert handler.event_queue.qsize() == 2
    
    handler.clear_queue()
    assert handler.event_queue.empty()
```

- [ ] **Step 2: 运行测试验证失败**

Run: `conda run -n stock_analysis pytest tests/unit/test_callback_handler.py::test_callback_handler_on_order_status -v`
Expected: FAIL with "No module named 'gmtrade_live.gateways.callback_handler'"

- [ ] **Step 3: 实现 CallbackHandler**

```python
# src/gmtrade_live/gateways/callback_handler.py
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import logging
from queue import Queue
from typing import Any

from gmtrade_live.models import OrderEvent, ExecutionEvent


class CallbackHandler:
    """回调处理器 - 转换 SDK 回报为内部事件并入队"""
    
    def __init__(self, logger: logging.Logger):
        self.event_queue: Queue = Queue()
        self.logger = logger
    
    def on_order_status(self, order: Any) -> None:
        """委托状态回调 - 只做转换和入队
        
        为什么只做转换和入队：
        - 回调在 SDK 线程中执行，不能阻塞
        - 业务逻辑在主线程中处理，保持单线程模型
        """
        try:
            event = self._convert_to_order_event(order)
            self.event_queue.put(event)
            self.logger.info(
                "order_callback_received order_id=%s symbol=%s status=%s",
                event.order_id,
                event.symbol,
                event.status,
            )
        except Exception as e:
            self.logger.error(
                "order_callback_error error=%s payload=%s",
                str(e),
                str(order)[:200],
                exc_info=True,
            )
    
    def on_execution_report(self, execution: Any) -> None:
        """成交回报回调 - 只做转换和入队"""
        try:
            event = self._convert_to_execution_event(execution)
            self.event_queue.put(event)
            self.logger.info(
                "execution_callback_received order_id=%s symbol=%s filled_volume=%s",
                event.order_id,
                event.symbol,
                event.filled_volume,
            )
        except Exception as e:
            self.logger.error(
                "execution_callback_error error=%s payload=%s",
                str(e),
                str(execution)[:200],
                exc_info=True,
            )
    
    def clear_queue(self) -> None:
        """清空队列中的旧事件
        
        为什么需要清空：
        - M1 是单笔验证，历史事件会污染本次验证
        - 每次 run() 前清空，确保只处理本次订单的回报
        """
        from queue import Empty

        while not self.event_queue.empty():
            try:
                self.event_queue.get_nowait()
            except Empty:
                break
    
    def _convert_to_order_event(self, order: Any) -> OrderEvent:
        """转换 SDK 委托对象为内部事件"""
        # 提取字段（适配 gm.api 的实际字段名）
        order_id = str(getattr(order, "cl_ord_id", ""))
        symbol = str(getattr(order, "symbol", ""))
        status_code = int(getattr(order, "status", 0))
        filled_volume = int(getattr(order, "filled_volume", 0))
        volume = int(getattr(order, "volume", 0))
        event_time = getattr(order, "created_at", datetime.now())
        
        # 状态码映射（根据 gm.api 实际定义）
        status_map = {
            1: "submitted",
            2: "partially_filled",
            3: "filled",
            5: "rejected",
            6: "cancelled",
        }
        status = status_map.get(status_code, f"unknown_{status_code}")
        
        return OrderEvent(
            order_id=order_id,
            symbol=symbol,
            status=status,
            filled_volume=filled_volume,
            remaining_volume=volume - filled_volume,
            event_time=event_time,
            message=f"Order status: {status}",
        )
    
    def _convert_to_execution_event(self, execution: Any) -> ExecutionEvent:
        """转换 SDK 成交对象为内部事件"""
        order_id = str(getattr(execution, "cl_ord_id", ""))
        symbol = str(getattr(execution, "symbol", ""))
        filled_volume = int(getattr(execution, "filled_volume", 0))
        filled_vwap = float(getattr(execution, "filled_vwap", 0.0))
        event_time = getattr(execution, "created_at", datetime.now())
        
        return ExecutionEvent(
            order_id=order_id,
            symbol=symbol,
            filled_volume=filled_volume,
            avg_price=Decimal(str(filled_vwap)),
            event_time=event_time,
        )
```

- [ ] **Step 4: 运行测试验证通过**

Run: `conda run -n stock_analysis pytest tests/unit/test_callback_handler.py -v`
Expected: PASS

- [ ] **Step 5: 写回调异常处理测试**

```python
# tests/unit/test_callback_handler.py (追加)

def test_callback_handler_on_order_status_error():
    """测试委托状态回调异常处理"""
    logger = logging.getLogger("test")
    handler = CallbackHandler(logger)
    
    # 传入无效对象
    handler.on_order_status(None)
    
    # 队列应该为空（异常被捕获）
    assert handler.event_queue.empty()

def test_callback_handler_on_execution_report_error():
    """测试成交回报回调异常处理"""
    logger = logging.getLogger("test")
    handler = CallbackHandler(logger)
    
    # 传入无效对象
    handler.on_execution_report(None)
    
    # 队列应该为空（异常被捕获）
    assert handler.event_queue.empty()
```

- [ ] **Step 6: 运行测试验证通过**

Run: `conda run -n stock_analysis pytest tests/unit/test_callback_handler.py -v`
Expected: ALL PASS

- [ ] **Step 7: 提交**

```bash
git add src/gmtrade_live/gateways/callback_handler.py tests/unit/test_callback_handler.py
git commit -m "feat(m1): implement callback handler

Add CallbackHandler for converting SDK callbacks to internal events:
- on_order_status(): convert order status callback to OrderEvent
- on_execution_report(): convert execution callback to ExecutionEvent
- clear_queue(): clear old events before new verification
- Exception handling: log errors without blocking callbacks

Callbacks only do conversion and enqueue, no business logic.
Business thread consumes events synchronously from queue.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: 扩展交易网关

**Files:**
- Modify: `src/gmtrade_live/gateways/gmtrade_trade_gateway.py`
- Test: `tests/unit/test_official_gateways.py`

- [ ] **Step 1: 写 submit_order 的测试**

```python
# tests/unit/test_official_gateways.py (追加到现有文件)
from decimal import Decimal
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import Mock
from gmtrade_live.gateways.gmtrade_trade_gateway import GMTradeQueryGateway
from gmtrade_live.models import OrderRequest

def test_submit_order_market_accepted():
    """测试市价单提交成功"""
    mock_api = Mock()
    mock_result = Mock()
    mock_result.cl_ord_id = "123456"
    mock_result.status = 1  # submitted
    mock_result.created_at = datetime.now(tz=ZoneInfo("Asia/Shanghai"))
    mock_api.order_volume.return_value = mock_result
    
    gateway = GMTradeQueryGateway(api_module=mock_api, account_id="test_account")
    
    request = OrderRequest(
        symbol="SHSE.600036",
        volume=100,
        side="sell",
        price_type="market",
        price=None,
    )
    
    result = gateway.submit_order(request)
    
    assert result.accepted is True
    assert result.order_id == "123456"
    mock_api.order_volume.assert_called_once()

def test_submit_order_limit_accepted():
    """测试限价单提交成功"""
    mock_api = Mock()
    mock_result = Mock()
    mock_result.cl_ord_id = "123456"
    mock_result.status = 1
    mock_result.created_at = datetime.now(tz=ZoneInfo("Asia/Shanghai"))
    mock_api.order_volume.return_value = mock_result
    
    gateway = GMTradeQueryGateway(api_module=mock_api, account_id="test_account")
    
    request = OrderRequest(
        symbol="SHSE.600036",
        volume=100,
        side="sell",
        price_type="limit",
        price=Decimal("10.50"),
    )
    
    result = gateway.submit_order(request)
    
    assert result.accepted is True
    assert result.order_id == "123456"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `conda run -n stock_analysis pytest tests/unit/test_official_gateways.py::test_submit_order_market_accepted -v`
Expected: FAIL with "GMTradeQueryGateway.__init__() got an unexpected keyword argument 'account_id'"

- [ ] **Step 3: 先核对本地 SDK 的真实 API 名称**

```powershell
@'
import gm.api as api

names = sorted(name for name in dir(api) if "order" in name.lower() or "callback" in name.lower())
for name in names:
    print(name)
'@ | conda run -n stock_analysis python -
```

Expected: 输出本地 `gm.api` 中与委托、回调相关的方法名，后续实现必须以本地 SDK 为准，不得臆造接口名。

- [ ] **Step 4: 修改 GMTradeQueryGateway 初始化方法**

```python
# src/gmtrade_live/gateways/gmtrade_trade_gateway.py (修改 __init__)
class GMTradeQueryGateway:
    def __init__(self, api_module: Any | None = None, account_id: str | None = None) -> None:
        """初始化交易网关
        
        Args:
            api_module: gm.api 模块（可选，用于测试注入）
            account_id: 账户 ID（M1 新增，用于 submit_order）
        """
        self._api = api_module or importlib.import_module("gm.api")
        self._account_id = account_id
        self._callback_handler: Any | None = None  # M1 新增
```

- [ ] **Step 5: 实现 set_callback_handler 方法**

```python
# src/gmtrade_live/gateways/gmtrade_trade_gateway.py (在类中添加)
def set_callback_handler(self, handler: Any) -> None:
    """设置回调处理器并注册到 SDK
    
    为什么由 Gateway 负责注册：
    - CallbackHandler 不持有 SDK 对象
    - Gateway 负责 SDK 适配，Handler 负责事件转换
    - 职责分离更清晰
    """
    self._callback_handler = handler
    # 以下方法名以 Step 3 输出的本地 SDK 为准；若本地名称不同，必须同步调整。
    # 注册委托状态回调
    self._api.set_order_callback(handler.on_order_status)
    # 注册成交回报回调
    self._api.set_execution_report_callback(handler.on_execution_report)
```

- [ ] **Step 6: 实现 submit_order 方法**

```python
# src/gmtrade_live/gateways/gmtrade_trade_gateway.py (在类中添加)
from gmtrade_live.models import OrderRequest, OrderSubmitResult

def submit_order(self, request: OrderRequest) -> OrderSubmitResult:
    """提交卖单委托
    
    为什么使用 self._account_id：
    - 避免每次调用都传入 account_id
    - account_id 在初始化时确定，运行期不变
    """
    if not self._account_id:
        raise ServiceError(
            code="gmtrade.no_account_id",
            message="Gateway 未初始化 account_id，无法提交订单",
            retryable=False,
            context={},
        )
    
    # 构造 SDK 订单参数
    order_side = 2  # 2 = 卖出（根据 gm.api 定义）
    
    if request.price_type == "market":
        # 市价单
        raw_result = self._api.order_volume(
            symbol=request.symbol,
            volume=request.volume,
            side=order_side,
            order_type=2,  # 2 = 市价单
            position_effect=2,  # 2 = 平仓
            account=self._account_id,
        )
    elif request.price_type == "limit":
        # 限价单
        if request.price is None:
            raise ServiceError(
                code="gmtrade.missing_price",
                message="限价单必须指定价格",
                retryable=False,
                context={"symbol": request.symbol},
            )
        raw_result = self._api.order_volume(
            symbol=request.symbol,
            volume=request.volume,
            side=order_side,
            order_type=1,  # 1 = 限价单
            position_effect=2,
            price=float(request.price),
            account=self._account_id,
        )
    else:
        raise ServiceError(
            code="gmtrade.invalid_price_type",
            message=f"不支持的价格类型: {request.price_type}",
            retryable=False,
            context={"price_type": request.price_type},
        )
    
    # 转换结果
    if not raw_result:
        return OrderSubmitResult(
            accepted=False,
            order_id=None,
            symbol=request.symbol,
            message="SDK 返回空结果",
            raw_status="empty",
            event_time=datetime.now(tz=ZoneInfo("Asia/Shanghai")),
        )
    
    raw_result = _coerce_record(raw_result)
    status_code = int(_pick(raw_result, "status", default=0))
    order_id = str(_pick(raw_result, "cl_ord_id", default=""))
    
    # 状态码 1 表示已提交
    accepted = (status_code == 1)
    
    return OrderSubmitResult(
        accepted=accepted,
        order_id=order_id if accepted else None,
        symbol=request.symbol,
        message=f"Order {'accepted' if accepted else 'rejected'}",
        raw_status=str(status_code),
        event_time=_as_datetime_or_now(raw_result, field_name="created_at"),
    )
```

- [ ] **Step 7: 修改 _pick 函数支持默认值**

```python
# src/gmtrade_live/gateways/gmtrade_trade_gateway.py (修改 _pick)
def _pick(payload: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """从 payload 中提取字段，支持默认值"""
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    if default is not None:
        return default
    raise ServiceError(
        code="gmtrade.missing_field",
        message="掘金返回字段缺失",
        retryable=True,
        context={"keys": ",".join(keys), "payload": str(payload)},
    )
```

- [ ] **Step 8: 运行测试验证通过**

Run: `conda run -n stock_analysis pytest tests/unit/test_official_gateways.py::test_submit_order_market_accepted -v`
Expected: PASS

- [ ] **Step 9: 运行 M0 + M1 网关测试验证默认构造不回退**

Run: `conda run -n stock_analysis pytest tests/unit/test_official_gateways.py -v`
Expected: ALL PASS (包括 M0 和 M1 测试)

- [ ] **Step 10: 提交**

```bash
git add src/gmtrade_live/gateways/gmtrade_trade_gateway.py tests/unit/test_official_gateways.py
git commit -m "feat(m1): extend GMTradeQueryGateway with order submission

Add M1 capabilities to GMTradeQueryGateway:
- __init__: add account_id parameter for submit_order
- set_callback_handler(): register callbacks to SDK
- submit_order(): submit market/limit sell orders
- Support both market and limit orders

M0 compatibility maintained:
- M0 bootstrap construction remains unchanged
- All M0 tests still pass

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: 实现手动验证服务

**Files:**
- Create: `src/gmtrade_live/services/m1_manual_trade.py`
- Test: `tests/unit/test_m1_manual_trade.py`

- [ ] **Step 1: 写服务成功场景测试**

```python
# tests/unit/test_m1_manual_trade.py
import logging
import time
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
from unittest.mock import Mock
from gmtrade_live.services.m1_manual_trade import ManualTradeService
from gmtrade_live.models import OrderRequest, OrderSubmitResult, OrderEvent, ExecutionEvent
from gmtrade_live.gateways.callback_handler import CallbackHandler

def test_manual_trade_service_success():
    """测试验证成功场景：两类回报都收到"""
    logger = logging.getLogger("test")
    
    # Mock gateway
    mock_gateway = Mock()
    now = datetime.now(tz=ZoneInfo("Asia/Shanghai"))
    mock_gateway.submit_order.return_value = OrderSubmitResult(
        accepted=True,
        order_id="123456",
        symbol="SHSE.600036",
        message="Order accepted",
        raw_status="1",
        event_time=now,
    )
    
    # Mock callback handler
    callback_handler = CallbackHandler(logger)
    
    # Mock config
    mock_config = Mock()
    mock_config.account_id = "test_account"
    mock_config.timezone = "Asia/Shanghai"
    
    service = ManualTradeService(
        trade_gateway=mock_gateway,
        callback_handler=callback_handler,
        logger=logger,
    )
    
    # 在后台线程中模拟回报到达
    def simulate_callbacks():
        time.sleep(0.1)
        # 模拟委托状态回报
        callback_handler.event_queue.put(OrderEvent(
            order_id="123456",
            symbol="SHSE.600036",
            status="filled",
            filled_volume=100,
            remaining_volume=0,
            event_time=now,
            message="Order filled",
        ))
        # 模拟成交回报
        callback_handler.event_queue.put(ExecutionEvent(
            order_id="123456",
            symbol="SHSE.600036",
            filled_volume=100,
            avg_price=Decimal("10.45"),
            event_time=now,
        ))
    
    import threading
    thread = threading.Thread(target=simulate_callbacks)
    thread.start()
    
    # 执行验证
    report = service.run(
        config=mock_config,
        symbol="SHSE.600036",
        volume=100,
        price_type="market",
        price=None,
        timeout_seconds=5,
    )
    
    thread.join()
    
    assert report.success is True
    assert report.order_event_received is True
    assert report.execution_event_received is True
    assert report.filled_volume == 100
    assert report.avg_price == Decimal("10.45")
```

- [ ] **Step 2: 运行测试验证失败**

Run: `conda run -n stock_analysis pytest tests/unit/test_m1_manual_trade.py::test_manual_trade_service_success -v`
Expected: FAIL with "No module named 'gmtrade_live.services.m1_manual_trade'"

- [ ] **Step 3: 实现 ManualTradeService 框架**

```python
# src/gmtrade_live/services/m1_manual_trade.py
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import logging
import time
from queue import Empty
from typing import Any
from zoneinfo import ZoneInfo

from gmtrade_live.config import AppConfig
from gmtrade_live.gateways.callback_handler import CallbackHandler
from gmtrade_live.gateways.protocols import TradeGateway
from gmtrade_live.models import (
    OrderRequest,
    OrderEvent,
    ExecutionEvent,
    TradeReport,
)


class ManualTradeService:
    """手动验证服务 - 编排单笔卖单的提交和回报验证
    
    定位：这是 M1 的验证服务，不是未来正式的自动卖出执行层
    """
    
    def __init__(
        self,
        trade_gateway: TradeGateway,
        callback_handler: CallbackHandler,
        logger: logging.Logger,
    ):
        self._trade_gateway = trade_gateway
        self._callback_handler = callback_handler
        self._logger = logger
    
    def run(
        self,
        config: AppConfig,
        symbol: str,
        volume: int,
        price_type: str,
        price: Decimal | None,
        timeout_seconds: int,
    ) -> TradeReport:
        """执行手动卖单验证
        
        为什么是同步等待：
        - M1 只验证单笔订单，不需要并发处理
        - 同步模型更简单，易于调试
        - 符合基础设施层 spec 的单线程模型
        """
        started_at = datetime.now(tz=ZoneInfo(config.timezone))
        
        self._logger.info(
            "m1_manual_trade_starting symbol=%s volume=%s price_type=%s timeout=%s",
            symbol,
            volume,
            price_type,
            timeout_seconds,
        )
        
        # 1. 清空旧事件
        self._callback_handler.clear_queue()
        
        # 2. 构造请求
        request = OrderRequest(
            symbol=symbol,
            volume=volume,
            side="sell",
            price_type=price_type,
            price=price,
        )
        
        # 3. 提交委托
        self._logger.info("order_submit_request symbol=%s volume=%s", symbol, volume)
        submit_result = self._trade_gateway.submit_order(request)
        self._logger.info(
            "order_submit_result accepted=%s order_id=%s raw_status=%s",
            submit_result.accepted,
            submit_result.order_id,
            submit_result.raw_status,
        )
        
        # 4. 若提交失败，直接返回
        if not submit_result.accepted:
            return self._build_submit_failed_report(
                config=config,
                request=request,
                submit_result=submit_result,
                started_at=started_at,
            )
        
        # 5. 等待回报
        return self._wait_for_callbacks(
            config=config,
            request=request,
            submit_result=submit_result,
            started_at=started_at,
            timeout_seconds=timeout_seconds,
        )
```

- [ ] **Step 4: 实现 _wait_for_callbacks 方法**

```python
# src/gmtrade_live/services/m1_manual_trade.py (追加)
def _wait_for_callbacks(
    self,
    config: AppConfig,
    request: OrderRequest,
    submit_result: Any,
    started_at: datetime,
    timeout_seconds: int,
) -> TradeReport:
    """等待回报（同步）
    
    为什么基于总截止时间：
    - 避免每次 queue.get() 的独立超时累加
    - 确保总等待时间不超过 timeout_seconds
    """
    order_event_received = False
    execution_event_received = False
    last_order_status: str | None = None
    filled_volume = 0
    avg_price: Decimal | None = None
    
    deadline = time.time() + timeout_seconds
    order_id = submit_result.order_id
    
    while time.time() < deadline:
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        
        try:
            # 从队列拉取事件（带超时）
            event = self._callback_handler.event_queue.get(timeout=min(1.0, remaining))
            
            # 事件匹配规则
            if isinstance(event, OrderEvent):
                # 必须 order_id 匹配
                if event.order_id != order_id:
                    self._logger.info(
                        "order_event_ignored order_id=%s expected=%s",
                        event.order_id,
                        order_id,
                    )
                    continue
                
                order_event_received = True
                last_order_status = event.status
                self._logger.info(
                    "order_event_matched order_id=%s status=%s",
                    event.order_id,
                    event.status,
                )
            
            elif isinstance(event, ExecutionEvent):
                # 必须 order_id 匹配
                if event.order_id != order_id:
                    self._logger.info(
                        "execution_event_ignored order_id=%s expected=%s",
                        event.order_id,
                        order_id,
                    )
                    continue
                
                execution_event_received = True
                filled_volume += event.filled_volume  # 累加成交量
                avg_price = event.avg_price  # 保留最后一次均价
                self._logger.info(
                    "execution_event_matched order_id=%s filled_volume=%s avg_price=%s",
                    event.order_id,
                    event.filled_volume,
                    event.avg_price,
                )
            
            # 成功条件：两类回报都收到
            if order_event_received and execution_event_received:
                finished_at = datetime.now(tz=ZoneInfo(config.timezone))
                self._logger.info(
                    "m1_manual_trade_success order_id=%s filled_volume=%s",
                    order_id,
                    filled_volume,
                )
                return TradeReport(
                    account_id=config.account_id,
                    symbol=request.symbol,
                    requested_volume=request.volume,
                    price_type=request.price_type,
                    submit_accepted=True,
                    order_id=order_id,
                    order_event_received=True,
                    execution_event_received=True,
                    last_order_status=last_order_status,
                    filled_volume=filled_volume,
                    avg_price=avg_price,
                    success=True,
                    message="M1 verification completed successfully",
                    started_at=started_at,
                    finished_at=finished_at,
                )
        
        except Empty:
            continue
    
    # 超时：未同时收到两类回报
    return self._build_timeout_report(
        config=config,
        request=request,
        order_id=order_id,
        order_event_received=order_event_received,
        execution_event_received=execution_event_received,
        last_order_status=last_order_status,
        filled_volume=filled_volume,
        avg_price=avg_price,
        started_at=started_at,
    )
```

- [ ] **Step 5: 实现辅助方法**

```python
# src/gmtrade_live/services/m1_manual_trade.py (追加)
def _build_submit_failed_report(
    self,
    config: AppConfig,
    request: OrderRequest,
    submit_result: Any,
    started_at: datetime,
) -> TradeReport:
    """构造提交失败报告"""
    finished_at = datetime.now(tz=ZoneInfo(config.timezone))
    self._logger.info(
        "m1_manual_trade_failed reason=submit_rejected message=%s",
        submit_result.message,
    )
    return TradeReport(
        account_id=config.account_id,
        symbol=request.symbol,
        requested_volume=request.volume,
        price_type=request.price_type,
        submit_accepted=False,
        order_id=None,
        order_event_received=False,
        execution_event_received=False,
        last_order_status=None,
        filled_volume=0,
        avg_price=None,
        success=False,
        message=f"Order submission rejected: {submit_result.message}",
        started_at=started_at,
        finished_at=finished_at,
    )

def _build_timeout_report(
    self,
    config: AppConfig,
    request: OrderRequest,
    order_id: str,
    order_event_received: bool,
    execution_event_received: bool,
    last_order_status: str | None,
    filled_volume: int,
    avg_price: Decimal | None,
    started_at: datetime,
) -> TradeReport:
    """构造超时报告
    
    为什么要区分三种超时：
    - 帮助诊断问题：是委托回报丢失、成交回报丢失，还是两者都丢失
    - 便于后续优化：不同类型的超时可能需要不同的处理策略
    """
    finished_at = datetime.now(tz=ZoneInfo(config.timezone))
    
    if not order_event_received and not execution_event_received:
        message = "missing_both_events"
    elif not order_event_received:
        message = "missing_order_event"
    else:
        message = "missing_execution_event"
    
    self._logger.info(
        "m1_manual_trade_timeout order_id=%s message=%s",
        order_id,
        message,
    )
    
    return TradeReport(
        account_id=config.account_id,
        symbol=request.symbol,
        requested_volume=request.volume,
        price_type=request.price_type,
        submit_accepted=True,
        order_id=order_id,
        order_event_received=order_event_received,
        execution_event_received=execution_event_received,
        last_order_status=last_order_status,
        filled_volume=filled_volume,
        avg_price=avg_price,
        success=False,
        message=message,
        started_at=started_at,
        finished_at=finished_at,
    )
```

- [ ] **Step 6: 运行测试验证通过**

Run: `conda run -n stock_analysis pytest tests/unit/test_m1_manual_trade.py::test_manual_trade_service_success -v`
Expected: PASS

- [ ] **Step 7: 写超时场景测试**

```python
# tests/unit/test_m1_manual_trade.py (追加)

def test_manual_trade_service_timeout_missing_execution():
    """测试超时场景：只收到委托状态回报"""
    logger = logging.getLogger("test")
    
    mock_gateway = Mock()
    now = datetime.now(tz=ZoneInfo("Asia/Shanghai"))
    mock_gateway.submit_order.return_value = OrderSubmitResult(
        accepted=True,
        order_id="123456",
        symbol="SHSE.600036",
        message="Order accepted",
        raw_status="1",
        event_time=now,
    )
    
    callback_handler = CallbackHandler(logger)
    mock_config = Mock()
    mock_config.account_id = "test_account"
    mock_config.timezone = "Asia/Shanghai"
    
    service = ManualTradeService(
        trade_gateway=mock_gateway,
        callback_handler=callback_handler,
        logger=logger,
    )
    
    # 只放入委托状态回报
    def simulate_callbacks():
        time.sleep(0.1)
        callback_handler.event_queue.put(OrderEvent(
            order_id="123456",
            symbol="SHSE.600036",
            status="submitted",
            filled_volume=0,
            remaining_volume=100,
            event_time=now,
            message="Order submitted",
        ))
    
    import threading
    thread = threading.Thread(target=simulate_callbacks)
    thread.start()
    
    report = service.run(
        config=mock_config,
        symbol="SHSE.600036",
        volume=100,
        price_type="market",
        price=None,
        timeout_seconds=2,
    )
    
    thread.join()
    
    assert report.success is False
    assert report.order_event_received is True
    assert report.execution_event_received is False
    assert report.message == "missing_execution_event"
```

- [ ] **Step 8: 运行测试验证通过**

Run: `conda run -n stock_analysis pytest tests/unit/test_m1_manual_trade.py -v`
Expected: ALL PASS

- [ ] **Step 9: 提交**

```bash
git add src/gmtrade_live/services/m1_manual_trade.py tests/unit/test_m1_manual_trade.py
git commit -m "feat(m1): implement manual trade service

Add ManualTradeService for M1 verification:
- run(): orchestrate order submission and callback waiting
- _wait_for_callbacks(): synchronously wait for both event types
- Event matching: order_id
- Timeout handling: distinguish missing_order_event, missing_execution_event, missing_both_events
- Accumulation: sum filled_volume, keep last avg_price

Single-threaded synchronous model:
- Callbacks only convert and enqueue
- Business thread consumes events from queue
- Total deadline timeout, not per-get timeout

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: 扩展 CLI 和 Bootstrap

**Files:**
- Modify: `main.py`
- Modify: `src/gmtrade_live/bootstrap.py`
- Test: `tests/unit/test_main.py`

- [ ] **Step 1: 写 CLI 参数解析测试**

```python
# tests/unit/test_main.py (修改现有文件)
from decimal import Decimal

import pytest

from main import build_parser

def test_parser_m0_mode_default():
    """测试 M0 模式（默认）"""
    parser = build_parser()
    args = parser.parse_args(["--config", "config.yaml"])
    assert args.config == "config.yaml"
    assert args.mode == "m0"

def test_parser_m1_mode_market_order():
    """测试 M1 市价单参数"""
    parser = build_parser()
    args = parser.parse_args([
        "--config", "config.yaml",
        "--mode", "m1",
        "--symbol", "SHSE.600036",
        "--volume", "100",
        "--price-type", "market",
    ])
    assert args.mode == "m1"
    assert args.symbol == "SHSE.600036"
    assert args.volume == 100
    assert args.price_type == "market"
    assert args.price is None

def test_parser_m1_mode_limit_order():
    """测试 M1 限价单参数"""
    parser = build_parser()
    args = parser.parse_args([
        "--config", "config.yaml",
        "--mode", "m1",
        "--symbol", "SHSE.600036",
        "--volume", "100",
        "--price-type", "limit",
        "--price", "10.50",
    ])
    assert args.price == Decimal("10.50")

def test_parser_m1_rejects_nonpositive_volume():
    """测试 M1 拒绝非正数量"""
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([
            "--config", "config.yaml",
            "--mode", "m1",
            "--symbol", "SHSE.600036",
            "--volume", "0",
            "--price-type", "market",
        ])

def test_parser_m1_rejects_invalid_limit_price():
    """测试 M1 拒绝非法限价值"""
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([
            "--config", "config.yaml",
            "--mode", "m1",
            "--symbol", "SHSE.600036",
            "--volume", "100",
            "--price-type", "limit",
            "--price", "abc",
        ])
```

- [ ] **Step 2: 运行测试验证失败**

Run: `conda run -n stock_analysis pytest tests/unit/test_main.py::test_parser_m1_mode_market_order -v`
Expected: FAIL with "unrecognized arguments: --mode m1"

- [ ] **Step 3: 修改 main.py 增加 M1 参数**

```python
# main.py (完全替换)
from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
from pathlib import Path


def _positive_int(raw: str) -> int:
    value = int(raw)
    if value <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value


def _positive_decimal(raw: str) -> Decimal:
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError("must be a valid decimal") from exc
    if value <= Decimal("0"):
        raise argparse.ArgumentTypeError("must be greater than 0")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GMTrade live trading system")
    parser.add_argument("--config", required=True, help="Path to YAML config file")
    parser.add_argument(
        "--mode",
        default="m0",
        choices=["m0", "m1"],
        help="Run mode: m0 (connectivity check) or m1 (manual trade)",
    )
    
    # M1 专用参数
    parser.add_argument("--symbol", help="Symbol to trade (required for m1)")
    parser.add_argument("--volume", type=_positive_int, help="Volume to sell (required for m1)")
    parser.add_argument(
        "--price-type",
        choices=["market", "limit"],
        help="Price type (required for m1)",
    )
    parser.add_argument("--price", type=_positive_decimal, help="Limit price (required for limit orders)")
    parser.add_argument(
        "--timeout-seconds",
        type=_positive_int,
        default=60,
        help="Timeout for waiting callbacks (default: 60)",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    
    if args.mode == "m0":
        from gmtrade_live.bootstrap import run_m0_connectivity_check
        return run_m0_connectivity_check(Path(args.config))
    
    elif args.mode == "m1":
        # 参数校验
        if not all([args.symbol, args.volume, args.price_type]):
            print("Error: --symbol, --volume, --price-type are required for m1 mode")
            return 1
        
        if args.price_type == "limit" and not args.price:
            print("Error: --price is required for limit orders")
            return 1

        if args.price_type == "market" and args.price is not None:
            print("Error: --price is not allowed for market orders")
            return 1
        
        from gmtrade_live.bootstrap import run_m1_manual_trade
        return run_m1_manual_trade(
            config_path=Path(args.config),
            symbol=args.symbol,
            volume=args.volume,
            price_type=args.price_type,
            price=args.price,
            timeout_seconds=args.timeout_seconds,
        )
    
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 运行测试验证通过**

Run: `conda run -n stock_analysis pytest tests/unit/test_main.py -v`
Expected: ALL PASS

- [ ] **Step 5: 实现 run_m1_manual_trade**

```python
# src/gmtrade_live/bootstrap.py (追加)
from decimal import Decimal
from gmtrade_live.gateways.callback_handler import CallbackHandler
from gmtrade_live.services.m1_manual_trade import ManualTradeService


def run_m1_manual_trade(
    config_path: Path,
    symbol: str,
    volume: int,
    price_type: str,
    price: Decimal | None,
    timeout_seconds: int,
) -> int:
    """运行 M1 手动验证"""
    config = load_config(config_path)
    logger = setup_logging(config.strategy_name, config.log_dir)
    
    logger.info(
        "m1_manual_trade_starting symbol=%s volume=%s price_type=%s timeout=%s",
        symbol,
        volume,
        price_type,
        timeout_seconds,
    )
    
    # 初始化组件
    callback_handler = CallbackHandler(logger)
    gateway = GMTradeQueryGateway(account_id=config.account_id)
    gateway.connect(config)
    gateway.set_callback_handler(callback_handler)
    
    service = ManualTradeService(
        trade_gateway=gateway,
        callback_handler=callback_handler,
        logger=logger,
    )
    
    # 执行验证
    report = service.run(
        config=config,
        symbol=symbol,
        volume=volume,
        price_type=price_type,
        price=price,
        timeout_seconds=timeout_seconds,
    )
    
    # 输出 JSON 报告
    print(
        json.dumps(
            {
                "success": report.success,
                "order_id": report.order_id,
                "submit_accepted": report.submit_accepted,
                "order_event_received": report.order_event_received,
                "execution_event_received": report.execution_event_received,
                "filled_volume": report.filled_volume,
                "avg_price": str(report.avg_price) if report.avg_price else None,
                "message": report.message,
            },
            ensure_ascii=False,
        )
    )
    
    return 0 if report.success else 1
```

- [ ] **Step 6: 运行 M0 测试验证不回退**

Run: `conda run -n stock_analysis pytest tests/unit/test_main.py -v`
Expected: ALL PASS

- [ ] **Step 7: 提交**

```bash
git add main.py src/gmtrade_live/bootstrap.py tests/unit/test_main.py
git commit -m "feat(m1): extend CLI and bootstrap for M1 mode

Add M1 mode to CLI:
- --mode: m0 (default) or m1
- M1 parameters: --symbol, --volume, --price-type, --price, --timeout-seconds
- Parameter validation: required fields and limit order price check

Add run_m1_manual_trade() to bootstrap:
- Initialize callback handler and gateway
- Register callbacks to SDK
- Execute manual trade service
- Output JSON report

M0 compatibility maintained.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

- [ ] **Spec coverage check**

Reviewing spec sections:
- ✓ Data models (Task 1): OrderRequest, OrderSubmitResult, OrderEvent, ExecutionEvent, TradeReport
- ✓ Gateway protocol (Task 2): submit_order() added to TradeGateway
- ✓ Callback handler (Task 3): on_order_status, on_execution_report, clear_queue
- ✓ Gateway extension (Task 4): submit_order, set_callback_handler, account_id initialization
- ✓ Manual trade service (Task 5): run, _wait_for_callbacks, timeout handling
- ✓ CLI extension (Task 6): --mode, M1 parameters, run_m1_manual_trade
- ⚠ Task 7 will补齐乱序、重复回报、错误 `order_id` 和 fake SDK 集成测试

- [ ] **Placeholder scan**

Searching for red flags:
- ✓ No "TBD", "TODO", "implement later"
- ✓ No "add appropriate error handling" without code
- ✓ No "write tests for the above" without actual test code
- ✓ All code blocks are complete
- ✓ All file paths are exact
- ✓ All commands have expected output

- [ ] **Type consistency check**

Checking method signatures and types:
- ✓ OrderRequest fields consistent across all tasks
- ✓ OrderSubmitResult fields consistent
- ✓ submit_order(request: OrderRequest) -> OrderSubmitResult consistent
- ✓ TradeReport fields consistent
- ✓ Event types (OrderEvent, ExecutionEvent) consistent

All types match across tasks.

---

## Task 7: 补充测试

**Files:**
- Test: `tests/unit/test_m1_manual_trade.py` (追加)
- Test: `tests/integration/test_m1_manual_trade_service.py` (新建)

- [ ] **Step 1: 写回报乱序测试**

```python
# tests/unit/test_m1_manual_trade.py (追加)

def test_manual_trade_service_out_of_order_events():
    """测试回报乱序：成交回报先于委托状态回报到达"""
    logger = logging.getLogger("test")
    
    mock_gateway = Mock()
    now = datetime.now(tz=ZoneInfo("Asia/Shanghai"))
    mock_gateway.submit_order.return_value = OrderSubmitResult(
        accepted=True,
        order_id="123456",
        symbol="SHSE.600036",
        message="Order accepted",
        raw_status="1",
        event_time=now,
    )
    
    callback_handler = CallbackHandler(logger)
    mock_config = Mock()
    mock_config.account_id = "test_account"
    mock_config.timezone = "Asia/Shanghai"
    
    service = ManualTradeService(
        trade_gateway=mock_gateway,
        callback_handler=callback_handler,
        logger=logger,
    )
    
    # 先放入成交回报，再放入委托状态回报
    def simulate_callbacks():
        time.sleep(0.1)
        # 成交回报先到
        callback_handler.event_queue.put(ExecutionEvent(
            order_id="123456",
            symbol="SHSE.600036",
            filled_volume=100,
            avg_price=Decimal("10.45"),
            event_time=now,
        ))
        time.sleep(0.1)
        # 委托状态回报后到
        callback_handler.event_queue.put(OrderEvent(
            order_id="123456",
            symbol="SHSE.600036",
            status="filled",
            filled_volume=100,
            remaining_volume=0,
            event_time=now,
            message="Order filled",
        ))
    
    import threading
    thread = threading.Thread(target=simulate_callbacks)
    thread.start()
    
    report = service.run(
        config=mock_config,
        symbol="SHSE.600036",
        volume=100,
        price_type="market",
        price=None,
        timeout_seconds=5,
    )
    
    thread.join()
    
    # 乱序不影响成功
    assert report.success is True
    assert report.order_event_received is True
    assert report.execution_event_received is True
```

- [ ] **Step 2: 写重复回报测试**

```python
# tests/unit/test_m1_manual_trade.py (追加)

def test_manual_trade_service_multiple_execution_events():
    """测试重复成交回报：累加 filled_volume"""
    logger = logging.getLogger("test")
    
    mock_gateway = Mock()
    now = datetime.now(tz=ZoneInfo("Asia/Shanghai"))
    mock_gateway.submit_order.return_value = OrderSubmitResult(
        accepted=True,
        order_id="123456",
        symbol="SHSE.600036",
        message="Order accepted",
        raw_status="1",
        event_time=now,
    )
    
    callback_handler = CallbackHandler(logger)
    mock_config = Mock()
    mock_config.account_id = "test_account"
    mock_config.timezone = "Asia/Shanghai"
    
    service = ManualTradeService(
        trade_gateway=mock_gateway,
        callback_handler=callback_handler,
        logger=logger,
    )
    
    # 放入多次成交回报
    def simulate_callbacks():
        time.sleep(0.1)
        callback_handler.event_queue.put(OrderEvent(
            order_id="123456",
            symbol="SHSE.600036",
            status="partially_filled",
            filled_volume=50,
            remaining_volume=50,
            event_time=now,
            message="Partial filled",
        ))
        callback_handler.event_queue.put(ExecutionEvent(
            order_id="123456",
            symbol="SHSE.600036",
            filled_volume=50,
            avg_price=Decimal("10.40"),
            event_time=now,
        ))
        time.sleep(0.1)
        callback_handler.event_queue.put(ExecutionEvent(
            order_id="123456",
            symbol="SHSE.600036",
            filled_volume=50,
            avg_price=Decimal("10.50"),
            event_time=now,
        ))
    
    import threading
    thread = threading.Thread(target=simulate_callbacks)
    thread.start()
    
    report = service.run(
        config=mock_config,
        symbol="SHSE.600036",
        volume=100,
        price_type="market",
        price=None,
        timeout_seconds=5,
    )
    
    thread.join()
    
    assert report.success is True
    assert report.filled_volume == 100  # 50 + 50
    assert report.avg_price == Decimal("10.50")  # 最后一次
```

- [ ] **Step 3: 写历史脏事件测试**

```python
# tests/unit/test_m1_manual_trade.py (追加)

def test_manual_trade_service_ignore_mismatched_order_id():
    """测试忽略提交后到达的其他 order_id 事件"""
    logger = logging.getLogger("test")
    
    mock_gateway = Mock()
    now = datetime.now(tz=ZoneInfo("Asia/Shanghai"))
    mock_gateway.submit_order.return_value = OrderSubmitResult(
        accepted=True,
        order_id="123456",
        symbol="SHSE.600036",
        message="Order accepted",
        raw_status="1",
        event_time=now,
    )
    
    callback_handler = CallbackHandler(logger)
    mock_config = Mock()
    mock_config.account_id = "test_account"
    mock_config.timezone = "Asia/Shanghai"
    
    service = ManualTradeService(
        trade_gateway=mock_gateway,
        callback_handler=callback_handler,
        logger=logger,
    )
    
    # 先放入错误订单的事件，再放入正确订单的事件
    def simulate_callbacks():
        time.sleep(0.1)
        callback_handler.event_queue.put(OrderEvent(
            order_id="old_order",
            symbol="SHSE.600036",
            status="filled",
            filled_volume=100,
            remaining_volume=0,
            event_time=now,
            message="Old order",
        ))
        callback_handler.event_queue.put(ExecutionEvent(
            order_id="old_order",
            symbol="SHSE.600036",
            filled_volume=100,
            avg_price=Decimal("9.00"),
            event_time=now,
        ))
        time.sleep(0.1)
        callback_handler.event_queue.put(OrderEvent(
            order_id="123456",
            symbol="SHSE.600036",
            status="filled",
            filled_volume=100,
            remaining_volume=0,
            event_time=now,
            message="Order filled",
        ))
        callback_handler.event_queue.put(ExecutionEvent(
            order_id="123456",
            symbol="SHSE.600036",
            filled_volume=100,
            avg_price=Decimal("10.45"),
            event_time=now,
        ))
    
    import threading
    thread = threading.Thread(target=simulate_callbacks)
    thread.start()
    
    report = service.run(
        config=mock_config,
        symbol="SHSE.600036",
        volume=100,
        price_type="market",
        price=None,
        timeout_seconds=5,
    )
    
    thread.join()
    
    assert report.success is True
    assert report.avg_price == Decimal("10.45")  # 不是旧订单的 9.00
```

- [ ] **Step 4: 运行所有单元测试**

Run: `conda run -n stock_analysis pytest tests/unit/ -v`
Expected: ALL PASS

- [ ] **Step 5: 写集成测试**

```python
# tests/integration/test_m1_manual_trade_service.py
import logging
import threading
import time
from datetime import datetime
from decimal import Decimal

import pytest
from zoneinfo import ZoneInfo

from gmtrade_live.gateways.callback_handler import CallbackHandler
from gmtrade_live.gateways.gmtrade_trade_gateway import GMTradeQueryGateway
from gmtrade_live.services.m1_manual_trade import ManualTradeService


class FakeGMApi:
    def __init__(self) -> None:
        self.order_callback = None
        self.execution_callback = None
        self.token = None
        self.endpoint = None

    def set_token(self, token: str) -> None:
        self.token = token

    def set_serv_addr(self, endpoint: str) -> None:
        self.endpoint = endpoint

    def set_order_callback(self, callback) -> None:
        self.order_callback = callback

    def set_execution_report_callback(self, callback) -> None:
        self.execution_callback = callback

    def order_volume(self, **kwargs):
        now = datetime.now(tz=ZoneInfo("Asia/Shanghai"))
        result = {
            "cl_ord_id": "ORDER_1",
            "status": 1,
            "created_at": now,
        }

        def emit_callbacks() -> None:
            time.sleep(0.1)
            if self.order_callback is not None:
                self.order_callback(
                    type(
                        "OrderPayload",
                        (),
                        {
                            "cl_ord_id": "ORDER_1",
                            "symbol": kwargs["symbol"],
                            "status": 3,
                            "filled_volume": kwargs["volume"],
                            "volume": kwargs["volume"],
                            "created_at": datetime.now(tz=ZoneInfo("Asia/Shanghai")),
                        },
                    )()
                )
            time.sleep(0.1)
            if self.execution_callback is not None:
                self.execution_callback(
                    type(
                        "ExecutionPayload",
                        (),
                        {
                            "cl_ord_id": "ORDER_1",
                            "symbol": kwargs["symbol"],
                            "filled_volume": kwargs["volume"],
                            "filled_vwap": 10.45,
                            "created_at": datetime.now(tz=ZoneInfo("Asia/Shanghai")),
                        },
                    )()
                )

        threading.Thread(target=emit_callbacks, daemon=True).start()
        return result


@pytest.mark.integration
def test_m1_manual_trade_fake_sdk_integration() -> None:
    """集成测试：使用假 SDK 串联 gateway、callback handler 和 service"""
    logger = logging.getLogger("test")
    fake_api = FakeGMApi()
    gateway = GMTradeQueryGateway(api_module=fake_api, account_id="test_account")
    callback_handler = CallbackHandler(logger)
    config = type(
        "Config",
        (),
        {
            "account_id": "test_account",
            "timezone": "Asia/Shanghai",
            "token": "demo-token",
            "gmtrade_endpoint": "127.0.0.1:7001",
        },
    )()

    gateway.connect(config)
    gateway.set_callback_handler(callback_handler)

    service = ManualTradeService(
        trade_gateway=gateway,
        callback_handler=callback_handler,
        logger=logger,
    )

    report = service.run(
        config=config,
        symbol="SHSE.600036",
        volume=100,
        price_type="market",
        price=None,
        timeout_seconds=5,
    )

    assert report.success is True
    assert report.order_event_received is True
    assert report.execution_event_received is True
    assert report.filled_volume == 100
    assert report.avg_price == Decimal("10.45")
```

- [ ] **Step 6: 运行集成测试**

Run: `conda run -n stock_analysis pytest tests/integration/test_m1_manual_trade_service.py -v -m integration`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add tests/unit/test_m1_manual_trade.py tests/integration/test_m1_manual_trade_service.py
git commit -m "test(m1): add comprehensive test coverage

Add unit tests:
- Out-of-order events: execution before order status
- Multiple execution events: accumulate filled_volume
- Old order_id events: ignore mismatched events
- Fake SDK integration: gateway + callback handler + service end-to-end

Add integration test:
- Fake SDK test for stable automated verification
- No GM terminal dependency

All edge cases covered per spec requirements.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: 最终验证与文档

**Files:**
- Update: `AGENTS.md`

- [ ] **Step 1: 运行所有自动化测试**

Run: `conda run -n stock_analysis pytest tests/unit tests/integration -v`
Expected: ALL PASS

- [ ] **Step 2: 运行 M0 验证（确保不回退）**

Run: `conda run -n stock_analysis python main.py --config config/sim_account.yaml`
Expected: JSON output with account info

- [ ] **Step 3: 执行 M1 手动冒烟验证**

```powershell
conda run -n stock_analysis python main.py --config config/sim_account.yaml --mode m1 --symbol SHSE.600036 --volume 100 --price-type market --timeout-seconds 60
```

Expected:
- 在账户具备对应可卖持仓、掘金终端运行且交易时段正常时，退出码为 `0`
- 标准输出为 JSON 报告，且 `success=true`
- 日志中包含 `order_submit_result`、`order_callback_received`、`execution_callback_received`、`m1_manual_trade_success`

If the preconditions are not met:
- 明确记录未执行原因或失败原因
- 不得把失败写成“已通过”

- [ ] **Step 4: 更新 AGENTS.md**

~~~markdown
# AGENTS.md (在“安装与运行”后追加)

### M1 手动验证
```bash
# M1 市价单验证
conda run -n stock_analysis python main.py --config config/sim_account.yaml --mode m1 \
  --symbol SHSE.600036 --volume 100 --price-type market --timeout-seconds 60

# M1 限价单验证
conda run -n stock_analysis python main.py --config config/sim_account.yaml --mode m1 \
  --symbol SHSE.600036 --volume 100 --price-type limit --price 10.50 \
  --timeout-seconds 120
```

预期输出：JSON 格式的验证报告
```json
{
  "success": true,
  "order_id": "123456",
  "submit_accepted": true,
  "order_event_received": true,
  "execution_event_received": true,
  "filled_volume": 100,
  "avg_price": "10.45",
  "message": "M1 verification completed successfully"
}
```
~~~

- [ ] **Step 5: 提交**

```bash
git add AGENTS.md
git commit -m "docs: update AGENTS with M1 verification commands

Add M1 manual trade verification commands and expected output.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 6: 最终检查清单**

验证以下项目：
- [ ] M0 模式仍然可用（`conda run -n stock_analysis python main.py --config config/sim_account.yaml`）
- [ ] M1 参数校验正常（缺少必填参数、非法数量、非法价格时报错）
- [ ] 所有自动化测试通过
- [ ] 代码有 Type Hints
- [ ] 关键逻辑有中文注释
- [ ] 金额使用 Decimal
- [ ] 无静默失败

---

## Execution Complete

M1 实施计划已完成。所有任务都包含：
- 完整的测试代码
- 完整的实现代码
- 明确的运行命令和预期输出
- 清晰的提交信息

关键设计点：
1. **单线程模型**：回调只做转换和入队，业务线程同步消费
2. **事件匹配**：依赖 `clear_queue()` + `order_id`，不使用本地时间硬过滤回报
3. **累计逻辑**：filled_volume 累加，avg_price 取最后一次
4. **超时区分**：missing_order_event, missing_execution_event, missing_both_events
5. **M0 兼容**：所有 M0 功能保持不变

下一步：选择执行方式（Subagent-Driven 或 Inline Execution）。
