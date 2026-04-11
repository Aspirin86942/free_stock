# M1 双向手工验证层设计

> 本文件定义 2026-04-09 起生效的 M1 新口径。

## 1. 背景

当前项目已经确认两条边界：

- 自动执行主线仍然只做自动卖出
- M1 不再定义为“手工卖单验证”，而是升级为“双向手工验证层”

这意味着 M1 负责提供一条可重复、可审计的手工交易验证路径，用于验证掘金柜台在 `buy` 和 `sell` 两个方向上的：

- 委托提交
- 查单确认
- 查成交确认
- 报告输出

M1 不负责扩展自动买入能力，也不改变后续自动执行主线的卖出边界。

## 2. 目标

将当前 `--mode m1` 扩展为统一的双向手工验证入口，使其支持：

- `--side buy`
- `--side sell`

并保持当前查询驱动主路径不变：

```text
submit_order -> query_order_status -> query_execution_reports -> 内部事件 -> 聚合报告
```

## 3. 范围与非范围

### 3.1 范围

- `m1` 命令支持 `--side buy|sell`
- 网关支持双向下单参数映射
- 服务层支持双向校验、查询与报告
- M1 JSON 输出增加交易方向
- M1 单元测试、集成测试、文档同步更新

### 3.2 非范围

- 自动买入主线
- 持续扫描全市场寻找买点
- 买入策略
- 买入后的持仓管理规则
- 数据库状态表
- 第二期状态机持久化实现

## 4. 方案比较

### 4.1 方案 A：保留 `m1`，新增 `--side buy|sell`

这是本次选择的方案。

优点：

- 与现有命令保持连续性
- 改动集中在参数解析、下单映射和报告字段
- 查询驱动主路径完全复用
- 文档与测试容易统一

缺点：

- 需要把部分“卖单验证”措辞收敛为“手工交易验证”

### 4.2 方案 B：新增独立模式承接买入

优点：

- 对现有 `m1` 的兼容性最好

缺点：

- 命令面重复
- 维护两套近似流程没有收益

### 4.3 方案 C：买入继续只保留独立脚本

优点：

- 主程序改动最少

缺点：

- 无法形成统一的 M1 能力定义
- 文档、测试、脚本三套口径会继续分裂

## 5. 核心设计

### 5.1 边界设计

M1 的新定义是：

- 它是**双向手工验证层**
- 它只解决“交易链路是否跑通”
- 它不承担自动交易策略职责

自动执行主线保持：

- 只识别卖出机会
- 只发出卖单
- 不因为 M1 增加 `buy` 而扩展自动买入职责

### 5.2 CLI 设计

保留现有：

```text
python main.py --config ... --mode m1 ...
```

新增参数：

```text
--side buy|sell
```

约束如下：

- `--side` 为必填，不给默认值
- `--price-type` 继续支持 `market|limit`
- `--price-type limit` 时必须提供 `--price`
- `--volume` 必须大于 0

这样可以避免在真实交易命令中对交易方向做隐式推断。

### 5.3 模型设计

#### `OrderRequest`

继续保留 `side` 字段，但其约束从“当前实现实际上只允许 `sell`”升级为：

- 允许值：`buy`、`sell`

#### `TradeReport`

新增：

- `side: str`

原因：

- 同一份报告必须能明确区分买入验证和卖出验证
- 后续审计、日志检索、问题追踪都需要方向字段

其余查询快照模型保持不变：

- `OrderSubmitResult`
- `OrderStatusSnapshot`
- `OrderExecutionSnapshot`

### 5.4 Gateway 设计

`GMTradeGateway.submit_order()` 从单向实现改为按 `request.side` 映射下单参数。

映射规则：

- `sell` -> `OrderSide_Sell + PositionEffect_Close`
- `buy` -> `OrderSide_Buy + PositionEffect_Open`

保留不变：

- `query_order_status()`
- `query_execution_reports()`

原因：

- 查询维度本来就与方向无关
- 方向变化只影响提交阶段，不影响后续按 `cl_ord_id` 收口

### 5.5 Service 设计

`ManualTradeService.run()` 新增参数：

- `side`

服务职责保持不变：

1. 校验输入
2. 构造 `OrderRequest`
3. 调用 `submit_order()`
4. 轮询查单
5. 在需要时查成交
6. 把查询结果转成内部事件
7. 聚合生成 `TradeReport`

新增约束：

- `side` 必须属于 `{"buy", "sell"}`
- 日志与报告必须带上 `side`

### 5.6 内部事件设计

M1 继续坚持当前查询驱动思想：

- 查询结果先转换为内部事件
- 聚合器消费内部事件
- 生成当前订单视图和最终报告

这条链路不因买卖方向发生变化而分叉。

后续若引入数据库与状态机，也仍然沿用：

```text
查询结果 -> 内部事件 -> 状态机/状态表
```

## 6. 成功判定

双向验证统一采用同一套判定规则：

- `submit_accepted=True`
- 且最终状态已确认

进一步细分：

- 若终态为 `rejected`、`cancelled`、`expired`、`done_for_day`、`stopped`，只要查单确认即可
- 若终态为 `filled`，必须同时确认成交明细
- 若状态停留在 `submitted`、`pending_new`、`partially_filled` 等非终态直到超时，则验证失败

## 7. 日志与输出

### 7.1 日志

M1 关键日志继续保留现有事件名，但日志内容改为“手工交易验证”口径，并在上下文字段中增加：

- `side`

至少覆盖：

- `m1_manual_trade_starting`
- `order_submit_request`
- `order_submit_result`
- `order_status_reconciled`
- `execution_status_reconciled`
- `m1_manual_trade_query_closed`
- `m1_manual_trade_timeout`
- `m1_manual_trade_failed`

### 7.2 JSON 输出

CLI 输出新增：

- `side`

示例：

```json
{
  "verification_passed": true,
  "side": "buy",
  "cl_ord_id": "ORDER_1",
  "broker_order_id": "BROKER_1",
  "submit_accepted": true,
  "order_status_confirmed": true,
  "execution_status_confirmed": true,
  "last_order_status": "filled",
  "rejection_reason": null,
  "filled_volume": 100,
  "avg_price": "10.450",
  "message": "交易状态已确认"
}
```

## 8. 测试设计

### 8.1 单元测试

至少补充以下测试：

- CLI 解析 `--side buy|sell`
- Gateway 在 `buy` 时映射为 `OrderSide_Buy + PositionEffect_Open`
- Gateway 在 `sell` 时保持 `OrderSide_Sell + PositionEffect_Close`
- `TradeReport` 包含 `side`
- Bootstrap 输出 JSON 包含 `side`
- `ManualTradeService` 在 `buy` 成功场景下仍能按查询驱动闭环

### 8.2 集成测试

至少补充一个 `buy` 场景，验证：

- 下单受理
- 查单确认终态
- 有成交时查成交确认数量与价格

原有 `sell` 场景保留，防止回归。

## 9. 文档变更要求

需要同步更新以下口径：

- M1 不是“手工卖单验证层”，而是“双向手工验证层”
- 自动主线仍然只做自动卖出
- 当前项目仍然是查询驱动

## 10. 实施原则

- 优先复用现有查询驱动主路径
- 不为 `buy` 再造一套独立服务
- 不把 M1 的双向能力扩散到自动执行主线
- 命名尽量保持兼容，只改真正错误的单向语义

## 11. 验收标准

本次变更完成后，应满足：

- `m1` 命令可显式传入 `--side buy|sell`
- `buy` 和 `sell` 都能走通统一的提交、查询、报告链路
- 自动执行主线边界不变，仍只做卖出
- 测试和文档与实现口径一致
