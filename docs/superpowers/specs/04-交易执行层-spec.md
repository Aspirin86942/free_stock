# 交易执行层 Spec

## 1. 文档目标

本文定义第一期实盘执行系统的交易执行层边界、执行流程、状态收口规则、异常处理策略和验收标准。

交易执行层只负责一件事：把已经被批准的卖出信号安全地变成一次可跟踪的卖单执行过程。

## 2. 本层定位

交易执行层统一负责：

- 接收核心决策层输出的卖出信号
- 生成并提交卖出委托
- 跟踪委托状态和成交回报
- 更新逐标的执行状态
- 防止重复卖单

本层不是规则判断层，也不是原始接口适配层。

## 3. 范围与非范围

### 3.1 本层范围

- 接收 `can_execute = true` 的卖出信号
- 生成卖出请求并调用数据接入层下单
- 记录委托提交结果
- 接收回报事件并更新执行状态
- 对同一标的执行重复发单拦截

### 3.2 不在本层范围

- 止盈止损判断
- 行情读取和持仓读取
- 配置加载和调度
- 原始回报对象解析

## 4. 与里程碑关系

交易执行层直接支撑以下里程碑：

- `M3 自动卖出执行闭环`
- `M4 测试、日志与稳定运行`

`M3` 是否成立，最终要看本层能否把“卖出信号”稳定收口成“委托结果和成交状态”。

## 5. 输入、输出与依赖

### 5.1 输入

- 核心决策层输出的卖出信号
- 当前逐标的状态
- 数据接入层返回的委托提交结果
- 数据接入层输出的委托和成交回报事件

### 5.2 输出

- 卖出委托请求
- 执行结果快照
- 状态更新结果
- 审计日志

### 5.3 依赖

- 数据接入层的下单能力和回报事件
- 核心决策层的卖出许可结论
- 基础设施层的日志和运行上下文

## 6. 执行流程

第一期标准执行流程如下：

1. 接收核心决策层输出的卖出信号。
2. 再次检查该标的当前是否已有未完成卖单。
3. 构造卖出请求并提交给数据接入层。
4. 若接口受理成功，则把状态更新为 `submitted`。
5. 若接口受理失败，则把状态更新为 `failed` 并记录原因。
6. 接收委托和成交回报，并按回报持续更新状态。
7. 当状态进入 `filled`、`cancelled` 或明确失败状态后，本次执行结束。

## 7. 防重复卖单规则

第一期最核心的执行约束就是防重复卖单。

必须遵守以下规则：

- 同一标的在存在未完成卖单时，禁止再次主动提交卖单
- `submitted` 和 `partially_filled` 状态下只能跟踪回报，不能重复发单
- `filled` 状态下不允许再次对同一批已卖完持仓发起执行
- 一个标的的执行状态不能覆盖另一个标的

### 7.1 原子操作：检查并提交

为了避免竞态条件，检查状态和提交订单必须是**原子操作**：

```python
def submit_sell_order(
    symbol: str,
    volume: int,
    state_manager: PositionStateManager,
    gateway: TradeGateway
) -> bool:
    """原子操作：检查状态并提交订单"""
    
    # 1. 再次检查是否有未完成订单（最后一道防护）
    if state_manager.has_open_order(symbol):
        logger.warning(f"duplicate_order_blocked symbol={symbol}")
        return False
    
    # 2. 立即标记为 submitting，防止重复
    state_manager.update_state(symbol, PositionState.submitting)
    
    # 3. 提交订单
    try:
        result = gateway.submit_order(symbol, volume)
        
        if result.accepted:
            # 4. 更新为 submitted
            state_manager.update_state(
                symbol,
                PositionState.submitted,
                order_id=result.order_id
            )
            return True
        else:
            # 5. 提交失败，更新为 failed
            state_manager.update_state(
                symbol,
                PositionState.failed,
                message=result.message
            )
            return False
    
    except Exception as e:
        # 6. 异常，更新为 failed
        state_manager.update_state(
            symbol,
            PositionState.failed,
            message=str(e)
        )
        logger.error(f"order_submit_error symbol={symbol} error={e}", exc_info=True)
        return False
```

### 7.2 为什么需要"再次检查"

虽然核心决策层已经检查过状态，但交易执行层仍需要**再次检查**，原因：

1. **防御性编程** - 即使上游逻辑有 bug，也不会导致重复发单
2. **时间窗口** - 从决策到执行之间可能收到回报，状态已变化
3. **最后一道防护** - 交易执行层是最接近外部接口的层，必须保证安全

## 8. 状态收口规则

建议最小执行状态如下：

| 状态 | 含义 |
| --- | --- |
| `submitting` | 正在提交卖单 |
| `submitted` | 已提交，等待回报 |
| `partially_filled` | 部分成交 |
| `filled` | 全部成交完成 |
| `cancelled` | 已撤单 |
| `failed` | 提交失败或执行异常 |

状态收口要求：

- 委托提交失败必须进入 `failed`
- 部分成交必须保持可继续跟踪状态
- 全部成交必须进入 `filled`
- 无法识别的回报必须进入明确异常路径并落日志

## 9. 执行输出契约

每次执行至少输出以下字段：

| 字段 | 说明 |
| --- | --- |
| `symbol` | 标的代码 |
| `order_id` | 委托标识 |
| `submit_result` | 提交是否成功 |
| `submit_time` | 提交时间 |
| `requested_volume` | 请求卖出数量 |
| `filled_volume` | 已成交数量 |
| `remaining_volume` | 剩余数量 |
| `execution_state` | 当前执行状态 |
| `message` | 执行说明或错误原因 |

## 10. 异常处理策略

执行层异常口径如下：

- 下单前校验失败：禁止提交，并记录阻断原因
- 下单接口失败：进入 `failed`
- 回报长期未到：记录超时风险，由后续轮询继续跟踪
- 回报状态异常：记录错误并进入明确异常路径
- 状态回写失败：记录错误，不允许静默忽略

第一期不引入复杂自动补救动作，先保证错误可见、状态可查。

## 11. 日志与审计要求

本层至少记录以下事件：

- 卖出信号接收
- 重复卖单拦截
- 卖出请求提交
- 委托受理结果
- 委托状态变化
- 成交状态变化
- 执行失败原因

关键字段至少包含：

- 标的代码
- 委托编号
- 请求数量
- 成交数量
- 当前状态
- 时间
- 错误原因

## 12. 测试要求

本层至少覆盖以下测试：

- 接收到合法卖出信号后能成功生成卖出请求
- 已有未完成卖单时会被正确拦截
- 委托提交失败时进入 `failed`
- 部分成交后状态保持为可继续跟踪
- 全部成交后状态进入 `filled`
- 回报异常时能够落日志并进入明确异常状态

## 13. 本层完成定义

交易执行层可视为完成，至少需要满足以下条件：

- 能接收并执行卖出信号
- 能稳定提交卖出委托
- 能跟踪委托和成交回报
- 能正确完成状态收口
- 能防止重复卖单
- 关键执行过程具备可审计日志
