# M3 自动卖出重写设计

## 1. 目标

把当前 M3 从“复用 M2 决策函数 + 单独维护执行态 + 提交后只查一次”的实现，重写为一条完整的自动卖出执行链路：

- M3 同时维护 `M2` 决策状态和 `M3` 订单执行状态
- M3 每轮先更新决策状态，再驱动订单执行
- 新提交订单和已有在途订单都在本轮内做查询驱动收口
- CLI 同时输出决策状态和订单状态，形成统一观察视图

本设计是对 [2026-04-10-m3-auto-sell-execution-design.md](/D:/Program_python/free_stock/docs/superpowers/specs/2026-04-10-m3-auto-sell-execution-design.md) 的重写收敛版本。旧版设计里“只保留执行态”的边界过于收紧，无法满足当前对 M3 的真实使用预期：既要知道“为什么卖”，也要知道“卖到了哪一步”。

## 2. 核心判断

### 2.1 M3 不是单一状态机

M3 的真实运行链路里同时存在两类事实：

- 决策事实：当前策略为什么触发，当前持仓处于 `watching` 还是 `tombstone`
- 执行事实：当前订单是否已提交、部分成交、全部成交、撤单或失败

这两类事实存在因果关系，但不是同一种状态。

因此，M3 不应把 `M2` 的决策观察态和 `M3` 的订单执行态揉成一个大状态机；正确做法是保留两套状态，并在 M3 编排层把它们串起来，再统一投影到 CLI。

### 2.2 M3 是编排层，不是状态拼盘

M3 的职责不是重新发明第三套策略逻辑，而是把现有能力串成一条自动执行链：

```text
持仓 + 行情
-> M2 决策状态同步
-> M2DecisionEngine
-> 决策反馈回写
-> M3 订单执行状态机
-> 查询驱动收口
-> CLI 双状态投影
```

因此，M3 的关键不在“状态合并”，而在“决策状态机 + 订单状态机 + 编排层”三者协同。

## 3. 文件与命名

### 3.1 决策状态层

保留现有文件：

- `src/gmtrade_live/services/m2_state_manager.py`

保持职责不变：

- 同步 `watching/tombstone`
- 记录 `last_trigger_reason`
- 记录 `last_block_reason`
- 记录 `last_decision_at`

### 3.2 订单执行状态层

删除：

- `src/gmtrade_live/state.py`

新增：

- `src/gmtrade_live/services/m3_state_manager.py`

新文件导出以下名字：

- `M3ExecutionState`
- `M3ExecutionStateSnapshot`
- `M3PositionStateManager`

命名原则：

- `M2StateManager` 对应决策观察态
- `M3PositionStateManager` 对应按标的维护的订单执行态
- 不再保留泛化的 `PositionStateManager`、`PositionStateSnapshot`、`PositionState` 命名，避免和“持仓状态”概念混淆

## 4. 状态职责边界

### 4.1 M2 决策状态机

`M2StateManager` 继续负责以下事实：

- 当前是否仍在持仓观察集合中
- `watching/tombstone`
- `sellable_now`
- `volume`
- `available_volume`
- `last_trigger_reason`
- `last_block_reason`
- `last_decision_at`

它回答的问题是：

- 当前策略上该不该卖
- 为什么触发或为什么被挡住
- 某个持仓是不是刚消失

### 4.2 M3 订单执行状态机

`M3PositionStateManager` 负责以下事实：

- 当前是否存在 open order
- `cl_ord_id`
- `broker_order_id`
- `requested_volume`
- `filled_volume`
- `remaining_volume`
- `submit_accepted`
- `last_order_status`
- `rejection_reason`
- `avg_price`
- `event_time`
- `message`

执行状态机仍使用最小集合：

- `idle`
- `submitting`
- `submitted`
- `partially_filled`
- `filled`
- `cancelled`
- `failed`

它回答的问题是：

- 当前订单执行到了哪一步
- 有没有未完成订单
- 该标的是否还能继续提单

### 4.3 两套状态的关系

同一个 symbol 在同一轮中，允许同时存在：

- 决策状态：例如 `watching + take_profit_triggered`
- 订单状态：例如 `submitted`

CLI 和日志应同时展示这两组信息，而不是二选一。

## 5. M3ExecutionService 重写后的角色

`M3ExecutionService` 变成真正的编排层，同时持有：

- `decision_state_manager: M2StateManager`
- `execution_state_manager: M3PositionStateManager`
- `decision_engine: M2DecisionEngine`
- `trade_gateway`
- `market_gateway`

它不再构造“临时伪造的决策快照”来喂给 `M2DecisionEngine`，而是使用 `M2StateManager` 当前维护的真实决策状态。

## 6. 单轮执行流程

每轮固定按以下顺序执行：

1. 查询当前持仓
2. 过滤出 `volume > 0` 的持仓
3. 查询相关行情
4. 用当前持仓调用 `M2StateManager.sync_positions()`
5. 对每个 symbol 读取真实决策状态并调用 `M2DecisionEngine.evaluate(...)`
6. 把 `trigger_reason/block_reason/volume/available_volume/sellable_now` 回写到 `M2StateManager`
7. 对每个 symbol 进入四类分流之一：
   - `decision_skip`
   - `execution_blocked`
   - `execution_tracking`
   - `execution_submit`
8. 对新提交订单和已有 open order 统一进入本轮收口阶段
9. 生成 `M3RoundReport`

### 6.1 `decision_skip`

满足任一条件即进入此分支：

- `should_sell = false`
- `can_submit_sell = false`
- 当前无需要进入执行链的事实变化

此分支不生成 `m3_execution_detail`，但可以在后续需要时纳入更丰富的 round 统计。

### 6.2 `execution_blocked`

满足以下情形之一即进入阻断分支：

- 数量归整后非法
- 数量超过 `available_volume`
- 其他执行前安全校验不通过

阻断详情应同时带出：

- 决策态字段
- 数量规划字段
- 当前执行态字段（如有）

### 6.3 `execution_tracking`

当某标的已经存在 open order 时：

- 本轮不得重复发单
- 只进入查询驱动收口
- 若状态发生变化，则生成 `m3_execution_detail`

### 6.4 `execution_submit`

当满足：

- `DecisionResult.can_submit_sell = true`
- 数量规划合法
- 当前无 open order

则进入原子提交流程：

1. 最后一次检查 open order
2. 状态置为 `submitting`
3. 发起 `submit_order`
4. 同步受理成功则置为 `submitted`
5. 同步受理失败则置为 `failed`
6. 本轮立刻进入收口阶段，不允许“提交后只查一次就退出”

## 7. 本轮共享收口预算

### 7.1 参数

M3 新增 CLI 参数：

- `--reconcile-timeout-seconds`

语义：

- 默认值为 `5`
- 仅用于 `m3`
- 当前阶段先不进入配置文件，避免配置面继续膨胀

### 7.2 查询间隔

本轮收口查询间隔固定为：

- `0.5s`

与 `M1` 保持一致。

### 7.3 共享预算而非单票预算

`5s` 是本轮共享预算，不是每个 symbol 单独预算。

原因：

- M3 在连续运行时可能同时存在多只在途订单
- 若按“每单独立 5s”处理，一轮时长会随着 open order 数量线性膨胀
- 共享预算可以把单轮压力收口在可控范围内

### 7.4 批次轮询

收口流程按批次轮询执行：

1. 收集本轮需要跟踪的 symbol：
   - 新提交的订单
   - 轮前已存在的 open order
2. 对这批 symbol 逐个查 `query_order_status()`
3. 对状态为 `filled/partially_filled` 的 symbol 再查 `query_execution_reports()`
4. 把查询结果转换为内部执行事件
5. 更新 `M3PositionStateManager`
6. 若仍存在未到终态的订单且预算未耗尽，则 `sleep(0.5s)` 后继续下一批
7. 直到：
   - 全部订单进入终态
   - 或本轮共享预算耗尽

### 7.5 超时后的行为

若本轮共享预算耗尽但仍有 open order：

- 本轮报告保留当前最新执行态
- 不把未终态订单误判为失败
- 连续模式下由下一轮继续跟踪
- `--once` 下只返回“当前已知状态”，不声称已完成闭环

## 8. CLI 输出重写

保持三类输出：

- `m3_round_summary`
- `m3_block_detail`
- `m3_execution_detail`

但 `detail` 必须同时带出决策态和订单态字段。

### 8.1 `m3_block_detail`

在原有字段基础上补充：

- `decision_lifecycle_state`
- `decision_should_sell`
- `decision_can_submit_sell`
- `decision_trigger_reason`
- `decision_block_reason`

### 8.2 `m3_execution_detail`

在原有字段基础上补充：

- `decision_lifecycle_state`
- `decision_should_sell`
- `decision_can_submit_sell`
- `decision_trigger_reason`
- `decision_block_reason`

并保留执行字段：

- `execution_state`
- `cl_ord_id`
- `broker_order_id`
- `requested_volume`
- `filled_volume`
- `remaining_volume`
- `submit_accepted`
- `last_order_status`
- `rejection_reason`
- `avg_price`
- `event_time`
- `message`

这样 CLI 对单个 symbol 展示的是同一条自动卖出链路的双状态视图：

- 为什么触发
- 当前订单到哪一步

## 9. bootstrap 与 main 改动

### 9.1 `main.py`

对 `m3` 增加：

- `--reconcile-timeout-seconds`

仅 `m3` 模式注册该参数，不污染 `m0/m1/m2`。

### 9.2 `bootstrap.run_m3_execution()`

新增参数：

- `reconcile_timeout_seconds: int`

并传递给 `M3ExecutionService`。

`--once` 的语义更新为：

- 只跑一轮
- 但这“一轮”内部允许按共享预算持续收口

## 10. 测试设计

### 10.1 状态层测试

保留并强化：

- `M2StateManager` 的 `watching/tombstone`
- `last_trigger_reason/last_block_reason` 回写

新增：

- `M3PositionStateManager` 的 open order 识别
- 执行态字段更新
- 不被空值错误覆盖

### 10.2 M3 service 单测

至少覆盖：

- 先同步决策态，再调用 `M2DecisionEngine`
- 决策结果回写到 `M2StateManager`
- 新单提交后进入本轮批次轮询收口
- 已有 open order 本轮只跟踪不重复发单
- 多个在途订单共享 `5s` 收口预算
- 坏快照不会把 `broker_order_id` 和 `remaining_volume` 覆盖坏

### 10.3 CLI / bootstrap 单测

至少覆盖：

- `--reconcile-timeout-seconds`
- `m3_execution_detail` 含决策态字段
- `m3_block_detail` 含决策态字段
- `--once` 下仍然执行本轮收口

### 10.4 集成测试

至少覆盖：

- `M2StateManager + M2DecisionEngine + M3PositionStateManager + M3ExecutionService`
- 同一 symbol 的决策态与订单态联动
- 新提交单在本轮内被连续查询
- 连续模式下超时未收口的 open order 在下一轮继续跟踪

## 11. 提交拆分建议

为降低审查和回滚成本，建议按三段提交：

1. `refactor(m3): rename execution state manager and types`
   - 新增 `m3_state_manager.py`
   - 删除 `state.py`
   - 类型重命名与状态层测试

2. `feat(m3): rewrite service with decision and execution states`
   - `M3ExecutionService` 双 manager 编排
   - 本轮共享预算收口
   - service 单测

3. `feat(m3): expose dual-state cli output`
   - `main.py`
   - `bootstrap.py`
   - 集成测试
   - 文档同步

## 12. 非范围

本轮重写仍然不做：

- 自动买入
- callback 驱动主闭环
- 多账户并发
- 执行态持久化数据库
- 新价格策略配置

## 13. 完成定义

重写完成后，M3 至少满足：

- 同时维护决策状态和订单执行状态
- `M3ExecutionService` 不再伪造临时决策态
- `--once` 下新单和在途单都能在本轮内按 `0.5s` 连续查询收口
- 收口预算为每轮共享 `5s`
- CLI 同时展示决策态和订单态
- `M3PositionStateManager` 命名清晰且与 `M2StateManager` 对称
- 不回退当前 M0/M1/M2 能力
