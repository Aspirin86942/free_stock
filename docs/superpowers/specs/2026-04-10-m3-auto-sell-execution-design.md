# M3 自动卖出执行闭环设计

## 1. 目标

实现 M3 里程碑：系统能够在显式运行 `--mode m3` 时，复用 M2 的决策结果，对满足条件的标的执行自动卖出，并通过查询驱动链路完成委托状态与成交结果收口。

M3 的核心验收标准：

- 只做自动卖出，不做自动买入
- 只有显式运行 `--mode m3` 才允许真实发单
- 卖出判断复用 `M2DecisionEngine`，不新增第二套策略逻辑
- 卖出数量由正式配置 `sell_quantity_ratio` 决定，不设置默认值
- 卖出数量先基于总持仓计算，再按残仓规则提升或按市场规则向下归整
- 若按比例计算后留下的总仓残量低于最低申报单位，则优先尝试一次性整仓卖出
- 归整后若不满足 `available_volume` 校验，则直接阻断，不自动缩量
- 下单主链路采用查询驱动：`submit_order -> query_order_status -> query_execution_reports -> 内部执行事件 -> 执行态聚合`
- 同一标的存在未完成卖单时禁止重复发单
- CLI 输出结构化摘要、阻断详情和执行详情
- 保持 M0 / M1 / M2 能力不回退

## 2. 边界与非范围

### 2.1 M3 范围

- 复用 M2 的卖出策略判断
- 自动卖出执行编排
- 卖出数量计算与合法性校验
- 提交前重复卖单拦截
- 查询驱动的委托与成交收口
- 逐标的执行态管理
- 执行阻断事实输出
- 结构化 CLI / 日志输出

### 2.2 M3 非范围

- 自动买入
- 新策略类型
- callback 驱动主闭环
- 执行态数据库持久化
- 多账户和多策略编排
- 运行时动态切换模式

## 3. 设计原则

### 3.1 严格分层

M3 属于交易执行层，不承担策略判断层职责。

- M2 回答“当前策略上该不该卖”
- M3 回答“当前是否能安全卖出，以及卖到哪一步”
- M3 不重新计算止盈止损阈值
- M3 不维护独立于 M2 的第二套触发逻辑

### 3.2 显式触发

真实自动卖出只能由显式 `--mode m3` 触发。

- `m0` 仅做连通性检查
- `m1` 仅做手工验证
- `m2` 仅做 dry-run 观察
- `m3` 才允许真实自动卖出

任何模式都不允许在运行中自动切换到 `m3`。

### 3.3 只卖不买

M3 只消费卖出方向的决策结果，不允许扩展为自动买入。

- `M2DecisionEngine` 复用的是卖出逻辑
- `M3` 下单方向固定为 `sell`
- 即使后续 M1 保留双向手工验证能力，也不改变 M3 的自动执行边界

### 3.4 查询驱动主线

当前项目统一采用查询驱动主线：

```text
submit_order
-> query_order_status
-> query_execution_reports
-> 内部执行事件
-> 执行态聚合结果
```

M3 不依赖 callback 才能成立。后续如果接入 callback，也只能作为网关补充信息，而不是当前闭环成立的必要条件。

### 3.5 持续执行型触发

M3 采用持续执行型触发，而不是“单次触发只卖一笔”。

- 每一轮都先复用 M2 重新评估
- 只要某标的当前仍满足 `should_sell = true` 且 `can_submit_sell = true`
- 并且该标的没有未完成卖单
- 并且本轮卖量计算结果合法
- 那么本轮就允许继续卖出一笔

这意味着 M3 的行为语义是“持续减仓”，而不是“每次触发打一枪”。

## 4. 与 M2 的关系

M3 必须直接复用 `M2DecisionEngine` 的输出结果，不允许再复制一套策略判断代码。

标准链路如下：

```text
持仓 + 行情
-> M2DecisionEngine
-> DecisionResult
-> M3 执行前校验
-> submit_order
-> query_order_status
-> query_execution_reports
-> 执行态聚合
```

约束如下：

- `DecisionResult.should_sell` 是纯策略结论
- `DecisionResult.can_submit_sell` 是基于交易时段和当前可卖性的基础提交结论
- M3 只能在 `can_submit_sell = true` 的前提下继续执行
- M3 自己再补做卖量合法性和执行态校验

## 5. 配置契约

M3 新增正式配置字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `sell_quantity_ratio` | `Decimal` | 是 | 每轮卖出比例，基于 `position.volume` 计算 |

配置语义固定为：

- 不提供默认值
- 合法范围：`0 < sell_quantity_ratio <= 1`
- `1` 或 `1.0` 表示卖出当前总持仓的 100%
- `0.01` 表示卖出当前总持仓的 1%

配置校验失败时，系统启动应直接报错，不允许带着不完整的交易参数进入运行态。

## 6. 卖出流程

M3 每轮执行流程固定为：

1. 查询当前持仓和相关行情
2. 调用 `M2DecisionEngine` 生成全部 `DecisionResult`
3. 只对 `can_submit_sell = true` 的标的进入执行候选集
4. 对候选标的计算目标卖量
5. 若按比例计算后留下的总仓残量低于最低申报单位，则优先尝试整仓卖出
6. 若整仓卖出条件不成立，则对目标卖量做市场规则归整
7. 对最终目标量做 `available_volume` 校验和重复卖单校验
8. 校验失败则输出阻断事实，不发单
9. 校验通过则进入原子提交流程
10. 同步提交受理成功后，立即进入查询驱动收口链路
11. 后续轮次对在途订单只做跟踪，不重复提交

### 6.1 原子提交流程

提交流程必须遵守“检查并提交”的最后一道原子防护：

1. 最后一次检查当前标的是否已有未完成卖单
2. 若存在未完成卖单，立即阻断
3. 若不存在，则先把执行态更新为 `submitting`
4. 再发起 `submit_order`
5. 提交成功则更新为 `submitted`
6. 提交失败则更新为 `failed`

## 7. 卖出数量规则

### 7.1 计算顺序

卖出数量必须按以下顺序计算：

1. 用总持仓计算原始目标量  
   `raw_target_volume = floor(position.volume * sell_quantity_ratio)`
2. 计算原始总仓残量  
   `raw_remaining_total = position.volume - raw_target_volume`
3. 若 `0 < raw_remaining_total < minimum_lot_for_symbol` 且 `position.volume <= available_volume`，则优先把目标量提升为整仓卖出  
   `promoted_target_volume = position.volume`
4. 若整仓提升不成立，则先按市场规则对原始目标量做合法化处理  
   `normalized_target_volume = normalize(raw_target_volume)`
5. 校验最终目标量是否仍为合法申报数量
6. 校验最终目标量 `<= available_volume`

用户已明确确认：

- 卖出比例必须基于 `position.volume` 计算
- 不能改成基于 `available_volume` 直接算比例
- `available_volume` 只用于最终校验
- 若原始卖量会留下低于最低申报单位的总仓残量，则优先尝试整仓卖出
- 若整仓当前不可卖，则不做“整可用仓位”补齐，继续按原始目标量归整与校验
- 若校验失败则直接打回，不自动缩量，不自动补最小单位

这里的“整仓优先”是正式规则，但只在当前确实能整仓卖出的前提下生效，不是测试特例。  
例如：

- 总持仓 `250`、原始目标卖量 `201`、总仓剩余 `49`，若 `available_volume >= 250`，则目标量直接提升为 `250`
- 总持仓 `250`、当日可卖 `201`、原始目标卖量 `200`，由于当前不能整仓卖出，因此最终目标量仍为 `200`

### 7.2 非科创板规则

一期范围内，非科创板 A 股先统一按“100 股规则 + 零股不能拆碎”处理。

对总持仓为 `position.volume` 的标的，合法卖量 `q` 必须满足：

- `q > 0`
- 且满足下列任一条件：
  - `q % 100 == 0`
  - `(position.volume - q) % 100 == 0`

含义是：

- 可以卖出整手数量
- 也可以把最终剩余零股一次性一起卖掉
- 但不能把零股拆碎
- 如果原始比例卖量会留下不足 `100` 股的总仓残量，则优先整仓卖出

向下归整规则：

- 从 `raw_target_volume` 开始递减
- 取最近一个满足上述合法条件的数量
- 若最终找不到合法数量，则归整结果记为 `0`

### 7.3 科创板规则

一期范围内，`SHSE.688*` 视为科创板股票。

科创板卖出规则按以下口径处理：

- 若总持仓 `position.volume >= 200`，则单笔申报数量必须 `>= 200`
- 若 `0 < position.volume < 200`，则该笔只能一次性全部卖出
- 如果原始比例卖量会留下不足 `200` 股的总仓残量，则优先整仓卖出

向下归整规则：

- 若 `position.volume < 200`
  - 当 `raw_target_volume >= position.volume` 时，归整结果为 `position.volume`
  - 否则归整结果为 `0`
- 若 `position.volume >= 200`
  - 当 `raw_target_volume >= 200` 时，归整结果为 `raw_target_volume`
  - 否则归整结果为 `0`

### 7.4 数量阻断原因

M3 新增以下数量相关阻断原因：

- `sell_quantity_below_min_order`
- `sell_quantity_exceeds_available`

其中：

- `sell_quantity_below_min_order` 表示按比例计算并归整后，无法形成合法申报数量
- `sell_quantity_exceeds_available` 表示最终目标卖量已算出，但超过当前 `available_volume`

用户已明确确认：

- 若整仓提升后的目标量超过 `available_volume`，则视为当前不能整仓卖出
- 当前不引入“整可用仓位卖出”规则

## 8. 执行状态设计

M3 的执行态只表达“自动卖单当前执行到哪一步”，不承载 M2 的策略触发语义。

建议最小执行状态如下：

| 状态 | 含义 |
| --- | --- |
| `idle` | 当前无执行中的卖单 |
| `submitting` | 正在提交卖单 |
| `submitted` | 已提交，等待查询确认 |
| `partially_filled` | 部分成交 |
| `filled` | 全部成交完成 |
| `cancelled` | 已撤单或被撤销 |
| `failed` | 提交失败、查询确认拒绝或执行异常 |

这里不再保留 `triggered` 作为 M3 的持久执行态。触发与否属于 M2 决策层事实，不属于 M3 执行态。

### 8.1 状态流转

主状态流转固定为：

```text
idle
-> submitting
-> submitted
-> partially_filled
-> filled | cancelled | failed
```

补充约束：

- 提交前校验失败时，不进入 `submitting`
- 同步提交未受理时，直接进入 `failed`
- 查单返回部分成交时，进入 `partially_filled`
- 查单返回全成时，进入 `filled`
- 查单返回撤单、过期、明确拒单等终态时，进入 `cancelled` 或 `failed`
- 处于 `submitted` / `partially_filled` 的标的，后续轮次只能跟踪，不能再次提交

## 9. 查询驱动收口

M3 的收口方式固定为查询驱动，不以 callback 为必要条件。

标准流程：

1. 提交卖单，拿到同步提交结果
2. 主动调用 `query_order_status()` 确认委托状态
3. 若有成交，再调用 `query_execution_reports()` 确认成交明细
4. 把查询结果规范化为内部执行事件
5. 再由执行态聚合逻辑生成最终执行结果

M3 不应把供应商原始返回直接当成外部稳定契约。稳定契约应是内部执行事件和执行聚合结果，CLI JSON 只是外部投影。

## 10. 输出契约

M3 CLI 输出采用“轮次摘要 + 阻断详情 + 执行详情”的结构。

### 10.1 `m3_round_summary`

每轮至少输出以下字段：

- `kind`
- `round`
- `session_state`
- `position_count`
- `candidate_count`
- `blocked_count`
- `submitted_count`
- `open_order_count`
- `changed_symbol_count`
- `duration_ms`

### 10.2 `m3_block_detail`

每个被阻断的标的至少输出以下字段：

- `kind`
- `symbol`
- `trigger_reason`
- `requested_ratio`
- `total_volume`
- `available_volume`
- `raw_target_volume`
- `promotion_type`
- `normalized_target_volume`
- `block_reason`
- `evaluated_at`

### 10.3 `m3_execution_detail`

每个进入执行链并发生状态变化的标的至少输出以下字段：

- `kind`
- `symbol`
- `change_tags`
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

## 11. 日志与审计

M3 至少需要记录以下事件：

- 执行候选识别
- 数量归整结果
- 提交前阻断原因
- 重复卖单拦截
- 提交请求和同步提交结果
- 查单结果
- 查成交结果
- 执行状态变化
- 终态结果

关键字段至少包含：

- `symbol`
- `requested_volume`
- `available_volume`
- `cl_ord_id`
- `broker_order_id`
- `execution_state`
- `trigger_reason`
- `block_reason`
- `event_time`

## 12. 测试方式

### 12.1 触发方式测试

M3 的真实发单触发权限必须严格限定为显式 `--mode m3`。

至少验证：

- `m0` 不发单
- `m1` 只接受手工参数，不自动卖出
- `m2` 只输出观察结果，不自动卖出
- `m3` 才允许自动卖出

### 12.2 单元测试

至少覆盖：

- 非科创板数量归整
- 科创板数量归整
- 非科创板总仓残量低于 `100` 股时提升为整仓卖出
- 科创板总仓残量低于 `200` 股时提升为整仓卖出
- 数量归整后为 `0` 的阻断
- 数量超过 `available_volume` 的阻断
- 整仓提升后超过 `available_volume` 时，不回退到任意更小数量
- 当前不可整仓卖出时，不会因为可用仓位剩余零头而提升到整可用仓位卖出
- 已有未完成卖单时的重复提交拦截
- 同步提交失败时进入 `failed`
- 查询结果驱动的状态迁移

### 12.3 集成测试

至少覆盖：

- `M2DecisionEngine` 输出被 M3 正确消费
- 提交后查询委托状态
- 订单出现成交后查询成交明细
- 查询驱动执行态收口
- 同一标的在未完成订单存在时不会重复发单

### 12.4 仿真冒烟测试

仿真环境测试建议固定分两步：

1. 先运行 `--mode m2` 观察 1-3 分钟，确认哪些标的在持续触发
2. 再运行 `--mode m3`，使用较小 `sell_quantity_ratio` 和有限轮次做真实自动卖出验证

建议重点观察：

- 是否存在错误重复发单
- 数量是否合法
- 查询驱动收口是否稳定
- 连续触发时是否按预期持续减仓

## 13. 风险与运行约束

- 若 `sell_quantity_ratio` 很小，部分标的可能因最小申报单位限制而长期被阻断
- 若原始比例卖量会留下低于最低申报单位的总仓残量，M3 会优先整仓卖出，实际卖出比例可能高于配置比例
- 若 `sell_quantity_ratio` 足以形成合法申报数量且价格持续触发，M3 会在连续轮次中持续减仓
- 因此 M3 测试不应长时间无限运行，建议配合 `--max-rounds`
- `available_volume = 0` 的标的即使策略上应卖，也不得发单
- 仿真环境只能验证链路和规则，不等价于真实成交质量

## 14. 完成定义

M3 可视为完成，至少需要满足以下条件：

- 显式 `--mode m3` 才允许自动卖出
- M3 复用 M2 决策结果，不新增第二套卖出判断
- 正式配置 `sell_quantity_ratio` 生效且无默认值
- 卖出数量按总持仓计算，并完成残仓提升或市场规则归整
- 留下低于最低申报单位总仓残量时会优先整仓卖出
- 归整结果超过 `available_volume` 时会被显式阻断
- 提交、查单、查成交能够通过查询驱动完成执行收口
- 同一标的不会在存在未完成卖单时重复提交
- CLI 和日志具备结构化、可审计输出
