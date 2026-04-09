# 核心决策层 Spec

> 本文件已按 2026-04-10 的查询驱动架构修订。当前 `M2` 指的是“核心决策与状态管理 dry-run”，不再混入执行态和未完成委托检查。

## 1. 文档目标

本文定义第一期实盘执行系统中核心决策层的边界、职责、判断规则、输出契约和验收标准。

核心决策层的职责不是“替执行层管理订单”，而是稳定回答两个问题：

- 当前规则上是否应卖：`should_sell`
- 当前若存在执行层，是否允许提交：`can_submit_sell`

## 2. 本层定位

核心决策层统一负责：

- 对全部 `volume > 0` 的持仓做逐标的独立评估
- 维护逐标的决策态快照
- 计算止盈止损结论
- 生成可审计的触发原因和阻断原因
- 输出稳定的结构化决策事实，供 `M2` dry-run、`M3` 执行层和后续状态表消费

本层是系统的“决策中心”，不是“接口调用中心”，也不是“订单生命周期中心”。

## 3. 范围与非范围

### 3.1 本层范围

- 为每个 `volume > 0` 的持仓标的建立独立决策态
- 根据持仓成本、当前价格和阈值判断是否触发止盈或止损
- 明确区分 `should_sell` 与 `can_submit_sell`
- 明确区分 `trigger_reason` 与 `block_reason`
- 显式表达“有持仓但当前不可平仓”的情形
- 对持仓消失场景保留一轮墓碑态，支持审计和变化检测
- 输出逐标的决策结果、轮次摘要和变化事件

### 3.2 不在本层范围

- 配置加载、轮询调度和进程生命周期控制
- 持仓、行情、委托状态、成交明细的原始查询
- 自动发单、撤单、重试
- 未完成委托查询与正式防重复卖单
- `submitted`、`partially_filled`、`filled` 等执行态推进
- 执行态持久化恢复和数据库接入

## 4. 与里程碑关系

核心决策层直接支撑以下里程碑：

- `M2 核心决策与状态管理`
- `M3 自动卖出执行闭环`

其中：

- `M2` 的目标是稳定产出“决策事实”
- `M3` 的目标是消费这些决策事实，并结合查询驱动的执行事实完成自动卖出闭环

## 5. 输入、输出与依赖

### 5.1 输入

- 持仓快照列表
- 行情快照列表
- 当前交易时段状态
- 止盈比例和止损比例
- 当前轮之前的逐标的决策态快照

说明：

- `M2` 第一版不把“未完成委托信息”作为核心决策层输入
- 未完成委托检查属于 `M3` 执行层的防重复卖单职责

### 5.2 输出

- 逐标的 `DecisionResult`
- 逐标的 `DecisionPositionStateSnapshot`
- 轮次级别的 `M2RoundSummary`
- 变化级别的 `M2ChangeEvent`
- 面向后续状态机或状态表的稳定内部契约

### 5.3 依赖

- 基础设施层提供的交易时段判断
- 数据接入层提供的持仓和行情快照
- `M3` 执行层对本层输出的消费

说明：

- 核心决策层本身不依赖 callback
- 后续状态机应统一消费内部对象，而不是直接依赖 CLI 文本输出

## 6. 状态模型

### 6.1 M2 决策态

`M2` 只维护轻量决策态，最小生命周期如下：

| 状态 | 含义 |
| --- | --- |
| `watching` | 当前轮仍有 `volume > 0` 持仓，参与评估 |
| `tombstone` | 上一轮仍有持仓，本轮消失，保留一轮用于审计 |

约束如下：

- 状态粒度必须是 `symbol`
- 一个标的的状态变化不能影响其他标的
- 墓碑态不参与本轮决策，只用于变化检测和审计

### 6.2 决策态管理职责

`M2StateManager` 负责：

- 同步当前持仓集合
- 创建新出现标的的 `watching` 态
- 维护持续存在标的的最新决策反馈
- 处理“一轮墓碑后删除”的生命周期

`M2StateManager` 不负责：

- 止盈止损阈值计算
- 交易时段判断
- 未完成委托检查
- 发单和执行态更新

### 6.3 与执行态的关系

以下状态属于 `M3` 执行态，而不是 `M2` 决策态：

- `submitting`
- `submitted`
- `partially_filled`
- `filled`
- `cancelled`
- `failed`

因此：

- `M2` 不复用执行态状态机
- `M3` 应在执行层单独维护执行态
- `M2` 输出的是决策事实，不是订单生命周期事实

### 6.4 存储与恢复策略

**M0-M2：**

- 决策态只保存在内存
- 程序重启后从当前持仓重新建立 `watching` 态
- 不尝试根据未完成委托恢复执行态

**M3-M4：**

- 可在执行层引入持久化状态表
- 恢复逻辑基于“查询驱动的执行事实”而不是 callback 假设

## 7. 判断规则

### 7.1 评估对象

核心决策层评估对象是全部 `volume > 0` 的持仓标的，而不是仅评估 `available_volume > 0` 的持仓。

这意味着：

- `available_volume = 0` 的标的也必须出现在输出中
- 不能因为暂不可平仓就让该标的从结果中消失

### 7.2 触发规则

- 当 `current_price >= cost_price * (1 + take_profit_ratio)` 时，`should_sell = True`
- 当 `current_price <= cost_price * (1 - stop_loss_ratio)` 时，`should_sell = True`
- 否则 `should_sell = False`

### 7.3 可提交规则

`can_submit_sell = True` 需同时满足：

- 当前处于允许发单的交易时段
- 当前轮 `should_sell = True`
- `available_volume > 0`

否则 `can_submit_sell = False`

### 7.4 触发原因与阻断原因

`trigger_reason` 用于说明“为什么应卖”，第一版至少包括：

- `take_profit_triggered`
- `stop_loss_triggered`

`block_reason` 用于说明“为什么当前不能提交”，第一版至少包括：

- `price_not_reached`
- `not_in_trading_session`
- `temporarily_not_closable`
- `quote_missing`

### 7.5 暂不可平仓语义

当某标的满足止盈或止损，但 `available_volume = 0` 时：

- `should_sell = True`
- `can_submit_sell = False`
- `trigger_reason` 保持实际触发原因
- `block_reason = "temporarily_not_closable"`

### 7.6 缺行情语义

当某标的存在持仓，但本轮未拿到行情时：

- 该标的继续保留在状态管理中
- `should_sell = False`
- `can_submit_sell = False`
- `trigger_reason = None`
- `block_reason = "quote_missing"`

### 7.7 与重复卖单的边界

核心决策层不判断“当前是否已有未完成委托”。

正式的重复卖单阻断属于 `M3` 执行层，执行层需要在提交前基于查询结果做最后一道检查。

## 8. 输出契约

### 8.1 单标的决策结果

每个标的至少输出以下字段：

| 字段 | 说明 |
| --- | --- |
| `symbol` | 标的代码 |
| `should_sell` | 当前是否应卖 |
| `can_submit_sell` | 当前是否允许提交 |
| `trigger_reason` | 当前触发原因 |
| `block_reason` | 当前阻断原因 |
| `current_price` | 当前价格 |
| `cost_price` | 持仓成本 |
| `take_profit_price` | 止盈阈值 |
| `stop_loss_price` | 止损阈值 |
| `volume` | 当前持仓数量 |
| `available_volume` | 当前可平仓数量 |
| `sellable_now` | 当前是否可平仓 |
| `session_state` | 当前交易时段状态 |
| `evaluated_at` | 本轮评估时间 |

### 8.2 状态快照与变化事件

除单标的决策结果外，还必须具备：

- `DecisionPositionStateSnapshot`
  用于表达 `watching` / `tombstone` 生命周期及最近一次反馈
- `M2RoundSummary`
  用于表达每轮摘要
- `M2ChangeEvent`
  用于表达变化标的的结构化详情

这些对象共同构成 `M2` 对内稳定契约。CLI JSON 只是它们的投影，不是唯一消费方式。

## 9. 异常处理策略

第一期禁止把判断异常当作“未触发”静默吞掉。

处理口径如下：

- 持仓缺失关键字段：当前标的进入错误路径并落日志
- 行情缺失：当前标的进入 `quote_missing` 路径并落日志
- 阈值参数非法：直接阻止系统启动
- 状态不一致：记录结构化日志并停止隐式推进

## 10. 日志与审计要求

本层至少记录以下信息：

- `symbol`
- `current_price`
- `cost_price`
- `take_profit_price`
- `stop_loss_price`
- `volume`
- `available_volume`
- `should_sell`
- `can_submit_sell`
- `trigger_reason`
- `block_reason`
- 生命周期变化结果

要求：

- 变化标的必须可审计
- 缺行情和墓碑态必须有明确观察载体
- 日志内容应能支撑后续状态表或问题追踪

## 11. 测试要求

本层至少覆盖以下测试：

- 止盈触发正确
- 止损触发正确
- 未到阈值不触发
- 达到阈值但非交易时段时只能触发、不能提交
- 达到阈值但 `available_volume = 0` 时只能触发、不能提交
- `volume > 0` 且 `available_volume = 0` 的标的仍纳入输出
- 缺行情时进入 `quote_missing`
- 标的消失后进入一轮墓碑，再于下一轮删除
- 多标的状态互不污染

## 12. 本层完成定义

核心决策层可视为完成，至少需要满足以下条件：

- 能评估全部 `volume > 0` 的持仓
- 能按标的维护独立决策态
- 能正确完成止盈止损判断
- 能严格分离 `should_sell` 与 `can_submit_sell`
- 能严格分离 `trigger_reason` 与 `block_reason`
- 能显式表达暂不可平仓和缺行情场景
- 能输出稳定的轮次摘要和变化事件
- 输出结果可直接供后续状态机或状态表消费
