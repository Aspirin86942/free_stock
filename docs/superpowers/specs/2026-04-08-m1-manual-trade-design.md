# M1 手动卖单委托-回报链路设计

> 2026-04-09 实施校正：
> 真实仿真环境验证表明，掘金 SDK 回调未稳定送达到本地 `CallbackHandler`。
> 因此 M1 的闭环标准已调整为“主动查单/查成交确认最终状态”，回调仅保留为观测增强字段，不再作为成功前提。

## 1. 目标

实现 M1 里程碑："数据接入跑通 - 账户、持仓、行情、委托、回报链路可稳定调用"。

M1 的核心验收标准：
- 能手动发起一笔卖单请求
- 能提交委托并获得同步结果
- 能注册并接收委托状态回报、成交回报（若 SDK 实际推送）
- 能主动查询委托最终状态与成交明细
- 能输出结构化验证报告
- 保持 M0 现有能力不回退

## 2. 边界与非范围

### 2.1 M1 范围

- 手动触发卖单（通过 CLI 参数）
- 委托提交接口实现
- 回调注册与事件转换
- 同步等待回调并主动轮询委托状态/成交明细
- 输出验证报告

### 2.2 M1 非范围（留给 M2/M3）

- 自动卖出触发逻辑
- 止盈止损判断
- 卖出许可判断
- 防重复卖单正式逻辑
- 正式的执行状态机收口
- 更新 `PositionStateManager` 业务状态
- 成交后自动重查账户和持仓

## 3. 架构设计

### 3.1 核心流程

```
用户触发（CLI）
  ↓
ManualTradeService 验证参数
  ↓
GMTradeGateway.submit_order() 提交委托
  ↓
掘金 SDK 回调（可选）→ CallbackHandler 转换事件 → 放入 Queue
  ↓
ManualTradeService 在同一线程中同步消费 Queue，并定期主动查单
  ↓
查到终态后，如有需要继续补查成交明细
  ↓
输出 TradeReport（不更新业务状态，不重查账户）
```

### 3.2 线程模型

**单线程顺序处理模型**（符合基础设施层 spec）：
- SDK 回调在 SDK 的线程中执行，只做"转换 + 入队"
- 业务逻辑在主线程中执行，同步从 Queue 拉取事件
- 不创建独立的事件处理线程

### 3.3 成功标准

M1 验证成功的判定改为“最终状态已确认”，而不是“回调双到达”：

```text
submit_accepted = True
AND final_state_confirmed = True
```

其中：
- `rejected`、`cancelled`、`expired`、`done_for_day`、`stopped` 等终态，只要查单已确认，即可视为 M1 成功
- `filled` 必须同时确认成交明细（数量、价格），才视为 M1 成功
- `submitted`、`pending_new`、`partially_filled` 等非终态，即使查到状态，也不视为成功
- `callback_chain_closed` 仅表示“委托状态回报 + 成交回报都实际收到”，是观测指标，不再是成功前提

## 4. 数据模型设计

### 4.1 OrderRequest（卖单请求）

```python
@dataclass(frozen=True, slots=True)
class OrderRequest:
    symbol: str              # 标的代码，如 "SHSE.600036"
    volume: int              # 卖出数量
    side: str                # 固定为 "sell"
    price_type: str          # "market" 或 "limit"
    price: Decimal | None    # 限价单时必填，市价单为 None
```

### 4.2 OrderSubmitResult（委托提交结果）

```python
@dataclass(frozen=True, slots=True)
class OrderSubmitResult:
    accepted: bool           # 是否被接受
    order_id: str | None     # 委托编号（被拒绝时为 None）
    symbol: str
    message: str             # 提交结果描述
    raw_status: str          # 原始状态码，用于审计
    event_time: datetime
```

### 4.3 OrderEvent（委托状态回报）

```python
@dataclass(frozen=True, slots=True)
class OrderEvent:
    order_id: str
    symbol: str
    status: str              # 如 "submitted", "filled", "rejected"
    filled_volume: int       # 已成交数量
    remaining_volume: int    # 剩余数量
    event_time: datetime
    message: str
```

### 4.4 ExecutionEvent（成交回报）

```python
@dataclass(frozen=True, slots=True)
class ExecutionEvent:
    order_id: str
    symbol: str
    filled_volume: int       # 本次成交数量（单次回报）
    avg_price: Decimal       # 本次成交均价
    event_time: datetime
```

**说明**：
- `filled_volume` 是单次回报的成交量，不是累计值
- `avg_price` 是本次回报的成交均价

### 4.5 TradeReport（M1 验证报告）

```python
@dataclass(frozen=True, slots=True)
class TradeReport:
    account_id: str
    symbol: str
    requested_volume: int
    price_type: str
    submit_accepted: bool
    cl_ord_id: str | None
    broker_order_id: str | None
    order_event_received: bool      # 是否收到委托状态回报
    execution_event_received: bool  # 是否收到成交回报
    callback_chain_closed: bool     # 两类回调是否都实际收到
    order_status_confirmed: bool    # 是否已通过回调或查单确认委托状态
    execution_status_confirmed: bool  # 是否已通过回调或查成交确认成交明细
    last_order_status: str | None
    rejection_reason: str | None
    filled_volume: int
    avg_price: Decimal | None
    verification_passed: bool       # 最终状态是否已确认
    message: str
    started_at: datetime
    finished_at: datetime
```

**说明**：
- `cl_ord_id` 与 `broker_order_id` 分开保留，便于审计与问题排查
- `callback_chain_closed` 用于体现 SDK 回调链路是否真的闭合
- `verification_passed` 表示最终交易状态是否已确认，不再等价于“收到两类回调”
- 如果收到多次成交回报，`filled_volume` 按同一订单累计，`avg_price` 保留最后一次回报或最后一次查成交结果

## 5. 组件设计

### 5.1 CallbackHandler（回调处理器）

**文件**：`src/gmtrade_live/gateways/callback_handler.py`

**职责**：
1. 注册掘金 SDK 的委托状态回调和成交回调
2. 将原始回调对象转换为内部事件
3. 放入线程安全的 `queue.Queue`
4. 记录结构化日志

**核心接口**：
```python
class CallbackHandler:
    def __init__(self, logger: logging.Logger):
        self.event_queue: Queue = Queue()
        self.logger = logger
    
    def on_order_status(self, order) -> None:
        """委托状态回调 - 只做转换和入队"""
    
    def on_execution_report(self, execution) -> None:
        """成交回报回调 - 只做转换和入队"""
    
    def clear_queue(self) -> None:
        """清空队列中的旧事件"""
```

**职责边界**：
- `CallbackHandler` 不持有 SDK 对象，不负责回调注册
- 回调注册由 `GMTradeGateway.set_callback_handler()` 完成
- `CallbackHandler` 只提供回调函数和事件队列

**硬约束**：
- 回调函数内禁止：更新业务状态、调用其他服务、阻塞等待、启动线程
- 回调函数只做：数据转换、入队、记录日志、异常捕获

### 5.2 GMTradeGateway（交易网关）

**文件**：`src/gmtrade_live/gateways/gmtrade_trade_gateway.py`

**变更**：
- 保持 `GMTradeQueryGateway` 类名不变（或增加别名 `GMTradeGateway`）
- 保持 M0 现有查询能力：`get_cash()`, `get_positions()`
- 新增委托能力：`submit_order()`, `set_callback_handler()`
- 新增初始化参数：`account_id`（用于 `submit_order()`）

**核心接口**：
```python
class GMTradeQueryGateway(TradeGateway):  # 保持类名不变
    def __init__(self, api, account_id: str):
        self._api = api
        self._account_id = account_id
        self._callback_handler: CallbackHandler | None = None
    
    def get_cash(self, account_id: str) -> CashSnapshot: ...
    def get_positions(self, account_id: str) -> tuple[PositionSnapshot, ...]: ...
    
    def set_callback_handler(self, handler: CallbackHandler) -> None:
        """设置回调处理器并注册到 SDK"""
        self._callback_handler = handler
        # 将 handler.on_order_status 和 handler.on_execution_report
        # 注册到掘金 SDK 的回调机制
    
    def submit_order(self, request: OrderRequest) -> OrderSubmitResult:
        """提交卖单委托（使用初始化时的 account_id）"""
        # 使用 self._account_id 提交订单

# 可选：增加类型别名以提升语义
GMTradeGateway = GMTradeQueryGateway
```

**设计说明**：
- `submit_order()` 使用初始化时传入的 `account_id`，不需要每次调用时传入
- 回调注册由 `set_callback_handler()` 完成，将 `CallbackHandler` 的回调函数注册到 SDK
- Gateway 负责 SDK 适配，Handler 负责事件转换
- 保持类名不变，降低 M0 代码改动风险

### 5.3 ManualTradeService（手动验证服务）

**文件**：`src/gmtrade_live/services/m1_manual_trade.py`

**定位**：手动验证编排服务，不是未来正式的自动卖出执行层。

**核心流程**：
1. 校验输入参数
2. 构造 `OrderRequest`
3. 清空 `CallbackHandler` 的事件队列（避免历史脏事件）
4. 调用 `submit_order()`
5. 若同步提交失败，直接生成失败 `TradeReport`
6. 若同步提交成功，在同一线程中进入"等待确认"循环
7. 从 `CallbackHandler.event_queue` 同步拉取事件（`queue.get(timeout<=0.2)`）
8. 定期主动调用 `query_order_status()`；若状态为 `filled`，继续调用 `query_execution_reports()`
9. 事件匹配规则：
   - 必须 `order_id` 匹配
   - 必须 `event_time >= started_at`（忽略历史事件）
   - 不匹配的事件记录日志后忽略
10. 累计逻辑：
   - 收到 `OrderEvent`：标记 `order_event_received = True`，更新 `last_order_status`
   - 收到 `ExecutionEvent`：标记 `execution_event_received = True`，累加 `filled_volume`，更新 `avg_price`
11. 一旦查单确认终态，立即结束等待，不白等完整 `timeout_seconds`
12. 超时条件：基于"总截止时间"（`started_at + timeout_seconds`），而不是每次 `queue.get()` 的独立超时
13. 报告文案需区分：
    - `交易状态已确认，但回调链路未闭环`（终态已确认，但回调未收齐）
    - `委托已成交，但成交明细未确认`
    - `委托状态已确认但尚未到终态: <status>`
    - `missing_order_event` / `missing_execution_event` / `missing_both_events`
14. 输出结构化 `TradeReport`

**核心接口**：
```python
class ManualTradeService:
    def run(
        self,
        config: Config,
        symbol: str,
        volume: int,
        price_type: str,
        price: Decimal | None,
        timeout_seconds: int,
    ) -> TradeReport:
        """执行手动卖单验证"""
```

## 6. CLI 设计

### 6.1 参数扩展

```bash
python main.py --config <path> [--mode {m0|m1}] [M1 参数...]

M0 模式（默认）：
  --config CONFIG       配置文件路径

M1 模式：
  --mode m1             启用 M1 模式
  --symbol SYMBOL       标的代码（必填）
  --volume VOLUME       卖出数量（必填）
  --price-type {market|limit}  价格类型（必填）
  --price PRICE         限价（限价单必填）
  --timeout-seconds N   回报等待超时（默认 60）
```

### 6.2 命令行示例

```bash
# M0 连通性检查
python main.py --config config/sim_account.yaml

# M1 市价单验证
python main.py --config config/sim_account.yaml --mode m1 \
  --symbol SHSE.600036 --volume 100 --price-type market

# M1 限价单验证
python main.py --config config/sim_account.yaml --mode m1 \
  --symbol SHSE.600036 --volume 100 --price-type limit --price 10.50 \
  --timeout-seconds 120
```

### 6.3 输出格式

JSON 格式的验证报告：
```json
{
  "verification_passed": true,
  "cl_ord_id": "123456",
  "broker_order_id": "654321",
  "submit_accepted": true,
  "order_event_received": false,
  "execution_event_received": false,
  "callback_chain_closed": false,
  "order_status_confirmed": true,
  "execution_status_confirmed": true,
  "last_order_status": "filled",
  "filled_volume": 100,
  "avg_price": "10.45",
  "message": "交易状态已确认，但回调链路未闭环"
}
```

## 7. 日志设计

### 7.1 关键日志事件

- `m1_manual_trade_starting` - 服务启动
- `order_submit_request` - 委托提交请求
- `order_submit_result` - 委托提交结果
- `order_callback_received` - 收到委托状态回调
- `execution_callback_received` - 收到成交回调
- `order_event_matched` - 委托状态回报匹配成功
- `execution_event_matched` - 成交回报匹配成功
- `order_status_reconciled` - 主动查单得到委托状态
- `execution_status_reconciled` - 主动查成交得到成交明细
- `m1_manual_trade_success` - 验证成功
- `m1_manual_trade_query_closed` - 通过主动查询确认闭环
- `m1_manual_trade_timeout` - 等待超时
- `m1_manual_trade_failed` - 验证失败
- `order_callback_error` - 回调处理异常
- `execution_callback_error` - 回调处理异常

### 7.2 日志格式

沿用现有结构化日志风格：
```
{timestamp} {level} {strategy_name} {event} key1=value1 key2=value2
```

## 8. 错误处理

### 8.1 参数校验错误

- M1 模式缺少必填参数 → CLI 报错并退出
- 限价单缺少 `--price` → CLI 报错并退出
- 数量或价格非法 → CLI 报错并退出

### 8.2 委托提交错误

- 提交被拒绝 → `TradeReport.submit_accepted = False`
- SDK 异常 → 捕获并记录，返回失败报告

### 8.3 回报处理错误

- 回调解析失败 → 记录错误日志 + 原始载荷摘要，不影响其他回报
- 事件队列满 → 理论上不会发生（`Queue` 无界），但需要监控

### 8.4 超时错误

- 若主动查询已确认终态，但回调未收齐 → `verification_passed = True`，`message = "交易状态已确认，但回调链路未闭环"`
- 若已确认 `filled`，但成交明细仍未确认 → `verification_passed = False`，`message = "委托已成交，但成交明细未确认"`
- 若仅确认到 `submitted` / `partially_filled` 等非终态 → `verification_passed = False`，`message = "委托状态已确认但尚未到终态: <status>"`
- 若既无回调也无查询结果 → 使用 `missing_order_event`、`missing_execution_event`、`missing_both_events` 区分缺失情况

## 9. 测试策略

### 9.1 单元测试

- `main.py` 参数解析测试（M0/M1 模式切换）
- 模型转换测试（SDK 对象 → 内部事件）
- `CallbackHandler` 入队测试（使用假回调对象）
- `ManualTradeService` 成功场景测试（双回调闭环 或 主动查询确认终态）
- `ManualTradeService` 超时场景测试（只收到一类回报）
- `ManualTradeService` 提交失败场景测试
- **回报乱序测试**：成交回报先于委托状态回报到达
- **重复回报测试**：同一 `order_id` 收到多次成交回报，验证累加逻辑
- **历史脏事件测试**：队列中存在旧 `order_id` 的事件，验证被忽略
- **事件时间过滤测试**：`event_time < started_at` 的事件被忽略
- **order_id 不匹配测试**：其他订单的回报被忽略

### 9.2 集成测试

- 使用假 SDK 或桩对象模拟完整流程
- 验证超时机制基于"总截止时间"而非单次 `queue.get()` 超时
- 验证事件匹配规则（`order_id` + `event_time`）

### 9.3 真实环境验证

- 在掘金仿真账户中执行真实卖单
- **优先使用市价单或可立即成交的限价单**（避免长期挂单导致的假失败）
- 验证主动查单和查成交能确认最终状态
- 记录回调是否真实到达；若未到达，不影响 M1 成功判定
- 验证日志完整性和可审计性

## 10. 实施计划

### 10.1 文件清单

**新增文件**：
- `src/gmtrade_live/gateways/callback_handler.py`
- `src/gmtrade_live/services/m1_manual_trade.py`
- `tests/unit/test_callback_handler.py`
- `tests/unit/test_m1_manual_trade.py`
- `tests/integration/test_m1_manual_trade_service.py`

**修改文件**：
- `src/gmtrade_live/models.py` - 增加 M1 相关模型
- `src/gmtrade_live/gateways/protocols.py` - 扩展 `TradeGateway` 协议
- `src/gmtrade_live/gateways/gmtrade_trade_gateway.py` - 增加委托能力（保持类名不变，扩展功能）
- `src/gmtrade_live/bootstrap.py` - 增加 `run_m1_manual_trade()`
- `main.py` - 增加 `--mode` 和 M1 参数
- `tests/unit/test_main.py` - 增加 M1 参数测试
- `tests/unit/test_official_gateways.py` - 更新 Gateway 测试

**命名策略**：
- 保持 `GMTradeQueryGateway` 类名不变，直接扩展功能
- 或增加类型别名：`GMTradeGateway = GMTradeQueryGateway`
- 目标：最小化 M0 代码改动，降低回归风险

### 10.2 实施顺序

1. 扩展数据模型（`models.py`）
2. 扩展网关协议（`protocols.py`）
3. 实现回调处理器（`callback_handler.py`）
4. 扩展交易网关（`gmtrade_trade_gateway.py`）
5. 实现手动验证服务（`m1_manual_trade.py`）
6. 扩展 Bootstrap 和 CLI
7. 补充单元测试
8. 补充集成测试
9. 真实环境验证

## 11. 验收标准

M1 完成的充要条件：

1. **功能完整性**：
   - CLI 支持 `--mode m1` 和所有 M1 参数
   - 能提交市价单和限价单
   - 能注册并观测委托状态回报和成交回报（若 SDK 实际推送）
   - 能主动查询委托最终状态与成交明细
   - 能输出结构化验证报告
   - 报告中能区分 `callback_chain_closed` 与 `verification_passed`

2. **测试覆盖**：
   - 单元测试覆盖所有核心逻辑
   - 集成测试验证完整流程
   - 真实环境验证通过

3. **日志完整性**：
   - 关键事件都有日志
   - 日志包含足够的上下文信息
   - 异常都有错误日志

4. **M0 兼容性**：
   - M0 模式仍然可用
   - M0 相关测试不回退

5. **代码质量**：
   - 所有公共函数有 Type Hints
   - 关键业务逻辑有中文注释
   - 金额使用 `Decimal`
   - 无静默失败

## 12. 风险与限制

### 12.1 已知风险

1. **回调时序不确定**：成交回报可能先于委托状态回报到达（已通过乱序测试覆盖）
2. **回调可靠性不足**：真实仿真环境中，SDK 回调可能根本不送达本地处理器，因此 M1 已改为以主动查询收口
3. **部分成交场景**：M1 只做状态确认，不做后续业务状态机收口；`partially_filled` 仍视为未完成终态
4. **网络延迟**：超时时间需要根据实际环境调整
5. **限价单挂单风险**：限价单可能长期无法成交，导致超时（真实验证优先使用市价单）

### 12.2 M1 限制

- 只支持单笔手动卖单验证
- 不支持并发多笔订单
- 不更新业务状态
- 不做成交后的账户同步

这些限制将在 M2/M3 中解决。
