# M2 核心决策与状态管理 Dry-Run 设计

## 1. 目标

实现 M2 里程碑：系统能够在不发单的前提下，连续轮询账户当前持仓，按标的独立完成止盈止损判断、卖出许可判断和内存态状态管理，并输出结构化 dry-run 决策结果。

M2 的核心验收标准：
- 能连续轮询读取账户当前持仓
- 只读取当前持仓标的的行情
- 对全部 `volume > 0` 的持仓完成逐标的独立评估
- 明确区分 `should_sell` 与 `can_submit_sell`
- 明确区分 `trigger_reason` 与 `block_reason`
- 支持一轮墓碑态的内存状态管理
- 连续 dry-run 时能输出摘要与变化详情
- 保持 M0/M1 能力不回退

## 2. 边界与非范围

### 2.1 M2 范围

- 多标的内存态状态管理
- 固定止盈止损判断
- 卖出许可结论输出
- 交易时段阻断判断
- 暂不可平仓持仓的显式输出
- 连续轮询 dry-run 验证
- 变化摘要与结构化日志

### 2.2 M2 非范围（留给 M3）

- 自动发单
- 未完成委托查询与正式防重复卖单
- 委托状态机收口
- 成交回报驱动的执行态更新
- 执行态持久化恢复
- 数据库接入

## 3. 设计原则

### 3.1 严格分层

M2 只属于核心决策层，不承担交易执行层职责。

- M2 回答“策略上该不该卖”
- M2 回答“此刻如果有执行层，是否允许提交”
- M2 不回答“单子发到哪一步”
- M2 不回答“当前是否存在未完成委托”

### 3.2 电平触发

M2 采用电平触发，而不是锁存触发。

- 每一轮都基于当前持仓和当前行情重新判断
- 达到止盈/止损阈值时，`should_sell = True`
- 价格回到阈值内后，`should_sell` 恢复为 `False`
- M2 不负责“触发后等待执行”的锁存逻辑

### 3.3 决策与可执行性分离

必须明确区分：

- `should_sell`
  纯策略结论，表示按规则当前应卖
- `can_submit_sell`
  纯可执行性结论，表示当前若存在执行层，是否允许提交卖单

因此允许出现以下合法组合：

- `should_sell = True` 且 `can_submit_sell = True`
- `should_sell = True` 且 `can_submit_sell = False`
- `should_sell = False` 且 `can_submit_sell = False`

### 3.4 触发原因与阻断原因分离

必须明确区分：

- `trigger_reason`
  说明为什么当前应卖
- `block_reason`
  说明为什么当前不能提交

例如：

- 满足止盈，但当前非交易时段  
  `trigger_reason = "take_profit_triggered"`  
  `block_reason = "not_in_trading_session"`

- 满足止损，但当前 `available_volume = 0`  
  `trigger_reason = "stop_loss_triggered"`  
  `block_reason = "temporarily_not_closable"`

## 4. 核心语义

### 4.1 评估对象

M2 的评估对象是全部 `volume > 0` 的持仓标的，而不是仅评估 `available_volume > 0` 的持仓。

这意味着：

- `volume > 0` 但 `available_volume = 0` 的标的也必须纳入状态管理
- 这类标的要明确表达为“有持仓，但当前暂时不能平仓”
- 不能因为暂不可平仓就让标的从评估结果中消失

### 4.2 当前暂不可平仓的输出语义

当某个标的满足止盈/止损，但当前 `available_volume = 0` 时：

- `should_sell = True`
- `can_submit_sell = False`
- `trigger_reason` 为实际触发原因
- `block_reason = "temporarily_not_closable"`

### 4.3 非交易时段的输出语义

当某个标的满足止盈/止损，但当前处于非交易时段时：

- `should_sell = True`
- `can_submit_sell = False`
- `trigger_reason` 为实际触发原因
- `block_reason = "not_in_trading_session"`

### 4.4 墓碑态语义

当某个标的上一轮仍有 `volume > 0` 持仓，而本轮已从持仓列表中消失时：

- 不立即删除状态
- 将其转入一轮 `tombstone`
- 若下一轮仍不存在，则从内存状态中移除

墓碑态仅用于审计与变化输出，不再参与决策判断。

## 5. 架构设计

### 5.1 组件拆分

M2 采用三组件拆分：

1. `M2StateManager`
   维护逐标的内存决策态与墓碑态
2. `M2DecisionEngine`
   负责单标的纯决策评估
3. `run_m2_dry_run()`
   负责轮询编排、持仓/行情读取和输出控制

### 5.2 组件职责

#### 5.2.1 `M2StateManager`

职责：

- 维护当前观察集合
- 处理新出现标的
- 处理持续存在标的
- 处理标的消失后一轮墓碑
- 回写本轮决策反馈

不负责：

- 止盈止损判断
- 交易时段判断
- 行情读取
- 发单

#### 5.2.2 `M2DecisionEngine`

职责：

- 计算止盈阈值与止损阈值
- 判断是否达到卖出条件
- 判断当前是否允许提交
- 生成 `DecisionResult`

不负责：

- 内存状态集合维护
- 生命周期管理
- 委托检查
- 发单

#### 5.2.3 `run_m2_dry_run()`

职责：

- 初始化配置、日志和 gateway
- 控制连续轮询
- 每轮读取持仓与行情
- 调用状态管理器和决策引擎
- 输出摘要与变化详情

不负责：

- 单标的规则计算细节
- 状态集合内部迁移规则

## 6. 轮询主流程

### 6.1 标准流程

M2 标准轮询流程如下：

1. 启动 `main.py --mode m2`
2. 加载配置并初始化日志
3. 初始化交易 gateway、行情 gateway、`M2StateManager`、`M2DecisionEngine`
4. 进入连续 dry-run 轮询
5. 每轮先解析当前 `session_state`
6. 查询账户当前全部持仓
7. 过滤出全部 `volume > 0` 的持仓标的
8. 只对这些持仓标的查询行情
9. `M2StateManager` 基于持仓集合差异同步状态
10. `M2DecisionEngine` 对每个仍处于 `watching` 的标的逐个评估
11. 输出本轮摘要
12. 若检测到变化，输出变化详情
13. `sleep(poll_interval_seconds)` 进入下一轮

### 6.2 轮询频率

M2 第一版采用固定频率轮询：

- 默认连续 dry-run
- 频率复用现有 `poll_interval_seconds`
- 默认按 5 秒一轮理解
- 不做忙等
- 不并发多轮重入
- 某一轮超过轮询间隔时，记录 `round_overrun`，不补帧

### 6.3 CLI 入口

M2 复用现有 CLI：

```bash
python main.py --config <path> --mode m2 [--once] [--max-rounds N]
```

行为约定：

- 默认连续 dry-run
- `--once` 只执行一轮
- `--max-rounds N` 执行固定轮数后退出

## 7. 数据模型设计

### 7.1 `DecisionResult`

```python
@dataclass(frozen=True, slots=True)
class DecisionResult:
    symbol: str
    should_sell: bool
    can_submit_sell: bool
    trigger_reason: str | None
    block_reason: str | None
    current_price: Decimal
    cost_price: Decimal
    take_profit_price: Decimal
    stop_loss_price: Decimal
    volume: int
    available_volume: int
    sellable_now: bool
    session_state: str
    evaluated_at: datetime
```

#### `trigger_reason` 第一版枚举

- `take_profit_triggered`
- `stop_loss_triggered`

#### `block_reason` 第一版枚举

- `price_not_reached`
- `not_in_trading_session`
- `temporarily_not_closable`
- `position_missing`
- `quote_missing`

### 7.2 `DecisionPositionStateSnapshot`

```python
@dataclass(frozen=True, slots=True)
class DecisionPositionStateSnapshot:
    symbol: str
    lifecycle_state: str          # watching / tombstone
    has_position: bool
    sellable_now: bool
    volume: int
    available_volume: int
    first_seen_at: datetime
    last_seen_at: datetime
    disappeared_at: datetime | None
    tombstone_rounds: int
    last_trigger_reason: str | None
    last_block_reason: str | None
    last_decision_at: datetime
```

#### 生命周期定义

- `watching`
  当前轮仍有 `volume > 0` 持仓，参与评估
- `tombstone`
  上一轮仍有持仓，本轮消失，保留一轮用于审计

### 7.3 `EvaluatedSymbol`

```python
@dataclass(frozen=True, slots=True)
class EvaluatedSymbol:
    decision: DecisionResult
    state_snapshot: DecisionPositionStateSnapshot
```

## 8. 组件接口设计

### 8.1 `M2StateManager`

```python
class M2StateManager:
    def __init__(self, logger: logging.Logger | None) -> None: ...

    def sync_positions(
        self,
        positions: tuple[PositionSnapshot, ...],
        now: datetime,
    ) -> tuple[DecisionPositionStateSnapshot, ...]:
        """同步 watching / tombstone / remove"""

    def get_state(self, symbol: str) -> DecisionPositionStateSnapshot | None: ...

    def update_decision_feedback(
        self,
        symbol: str,
        *,
        trigger_reason: str | None,
        block_reason: str | None,
        volume: int,
        available_volume: int,
        sellable_now: bool,
        decision_time: datetime,
    ) -> DecisionPositionStateSnapshot:
        """回写本轮决策反馈"""

    def active_states(self) -> tuple[DecisionPositionStateSnapshot, ...]: ...
```

### 8.2 `M2DecisionEngine`

```python
class M2DecisionEngine:
    def evaluate(
        self,
        *,
        position: PositionSnapshot,
        quote: QuoteSnapshot,
        session_state: TradingSessionState,
        state_snapshot: DecisionPositionStateSnapshot,
        config: AppConfig,
        now: datetime,
    ) -> DecisionResult:
        """评估单个标的的应卖结论与可提交结论"""
```

### 8.3 `run_m2_dry_run()`

```python
def run_m2_dry_run(
    *,
    config_path: Path,
    once: bool,
    max_rounds: int | None,
) -> int:
    """执行 M2 连续 dry-run 验证"""
```

## 9. 决策规则

### 9.1 阈值计算

- `take_profit_price = cost_price * (1 + take_profit_ratio)`
- `stop_loss_price = cost_price * (1 - stop_loss_ratio)`

### 9.2 触发规则

- 当 `current_price >= take_profit_price` 时，`should_sell = True`
- 当 `current_price <= stop_loss_price` 时，`should_sell = True`
- 否则 `should_sell = False`

### 9.3 可提交规则

`can_submit_sell = True` 需同时满足：

- 当前处于允许发单的交易时段
- `available_volume > 0`
- 当前轮 `should_sell = True`

否则 `can_submit_sell = False`

### 9.4 缺行情处理

若某标的存在持仓，但本轮未拿到行情：

- 仍保留在状态管理中
- 生成结构化结果
- `should_sell = False`
- `can_submit_sell = False`
- `trigger_reason = None`
- `block_reason = "quote_missing"`

## 10. 输出策略

### 10.1 每轮摘要

每轮固定输出摘要，至少包含：

- `round`
- `session_state`
- `position_count`
- `watching_count`
- `tombstone_count`
- `should_sell_count`
- `can_submit_sell_count`
- `changed_symbol_count`
- `duration_ms`

### 10.2 变化详情

仅当标的出现以下变化时输出详情：

- `lifecycle_state` 变化
- `should_sell` 变化
- `can_submit_sell` 变化
- `trigger_reason` 变化
- `block_reason` 变化
- `volume` 变化
- `available_volume` 变化
- 标的进入 `tombstone`
- 标的从 `tombstone` 被删除
- `quote_missing` 的出现与恢复

### 10.3 变化标签建议

- `symbol_started_watching`
- `trigger_activated`
- `trigger_cleared`
- `submit_permission_granted`
- `submit_permission_blocked`
- `position_became_unsellable`
- `position_became_sellable`
- `entered_tombstone`
- `removed_after_tombstone`
- `quote_missing_detected`
- `quote_missing_recovered`

## 11. 测试策略

### 11.1 `M2DecisionEngine` 单元测试

至少覆盖：

- 止盈触发且可提交
- 止损触发且可提交
- 未到阈值不触发
- 达到阈值但非交易时段
- 达到阈值但 `available_volume = 0`
- `volume > 0` 且 `available_volume = 0` 时仍纳入输出
- 电平触发：价格回到阈值内后恢复不触发
- `trigger_reason` 与 `block_reason` 同时存在

### 11.2 `M2StateManager` 单元测试

至少覆盖：

- 新标的进入 `watching`
- 持续存在标的保持 `watching`
- 标的消失后进入一轮 `tombstone`
- `tombstone` 下一轮删除
- 多标的状态互不污染
- 决策反馈正确回写

### 11.3 编排层测试

至少覆盖：

- `--once` 仅执行一轮
- `--max-rounds N` 按轮数停止
- 无持仓时不查行情
- 只对持仓标的查行情
- 每轮打印摘要
- 仅变化标的打印详情
- 轮次耗时超出间隔时记录 `round_overrun`

### 11.4 假网关集成测试

至少覆盖：

- 标的从未触发到触发
- 标的从可平仓变为暂不可平仓
- 标的从持仓中消失并进入墓碑
- 非交易时段与交易时段切换
- 多标的并行评估互不干扰

## 12. 实施建议

### 12.1 新增文件

- `src/gmtrade_live/services/m2_state_manager.py`
- `src/gmtrade_live/services/m2_decision_engine.py`
- `tests/unit/test_m2_state_manager.py`
- `tests/unit/test_m2_decision_engine.py`
- `tests/integration/test_m2_dry_run.py`

### 12.2 修改文件

- `src/gmtrade_live/models.py`
- `src/gmtrade_live/bootstrap.py`
- `main.py`
- `tests/unit/test_main.py`

### 12.3 与现有 `state.py` 的关系

现有 `src/gmtrade_live/state.py` 明显偏执行态，包含：

- `submitting`
- `submitted`
- `partially_filled`
- `filled`
- `cancelled`
- `failed`

这些状态属于 M3 的执行态，不应直接承接 M2 主逻辑。M2 应新增独立的决策态状态管理实现，而不是复用执行态状态机。

## 13. 完成定义

M2 可视为完成，至少需要满足以下条件：

- 能连续 dry-run 轮询
- 只查询当前持仓标的行情
- 全部 `volume > 0` 的持仓都进入状态管理
- `should_sell` 与 `can_submit_sell` 严格分离
- `trigger_reason` 与 `block_reason` 严格分离
- 采用电平触发
- 支持一轮墓碑态
- 输出摘要稳定、变化详情可审计
- 测试可复现核心判断与状态演进

