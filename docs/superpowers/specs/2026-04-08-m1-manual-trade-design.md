# M1 双向手工验证查询收口设计

> 本文件为历史 M1 设计文档的统一修订版，当前以查询驱动口径为准。

## 1. 目标

实现 M1 里程碑：手工触发一笔 `buy/sell` 委托，提交到掘金柜台，并通过查询确认最终状态，输出结构化验证报告。

M1 的职责是验证交易链路，不负责自动买入，也不改变自动执行主线只做自动卖出的边界。

## 2. 范围与非范围

### 2.1 M1 范围

- 通过 CLI 手工触发一笔 `buy/sell` 委托
- 调用掘金接口提交委托
- 轮询查询订单状态
- 在订单出现成交相关状态时查询成交明细
- 把查询结果先整理为内部事件，再聚合出最终报告
- 输出结构化 JSON，供人工核对和脚本消费

### 2.2 M1 非范围

- 自动卖出触发逻辑
- 自动买入触发逻辑
- 止盈止损判断
- 卖出许可判断
- 正式状态表
- 数据库持久化
- 成交后重查账户和持仓

## 3. 架构设计

### 3.1 核心流程

```text
用户触发（CLI）
  ↓
ManualTradeService 校验参数
  ↓
GMTradeQueryGateway.submit_order() 提交委托
  ↓
GMTradeQueryGateway.query_order_status() 轮询查单
  ↓
若状态涉及成交，则调用 query_execution_reports()
  ↓
查询结果转成内部事件
  ↓
聚合出 TradeReport
  ↓
输出 JSON 报告
```

### 3.2 设计原则

- 主链路统一使用查询收口
- `buy` 与 `sell` 共用一套服务和一套聚合逻辑
- 供应商返回的原始结构必须先标准化
- 查询结果先形成内部事件，再进入聚合逻辑
- 第一阶段只做内存聚合，不引入数据库
- 后续接入状态表后，复用“内部事件 -> 状态机”这条链路

### 3.3 成功标准

M1 验证成功的判定是：

```text
submit_accepted = True
AND final_state_confirmed = True
```

其中：

- `rejected`、`cancelled`、`expired`、`done_for_day`、`stopped` 等终态，只要查单已确认，即可视为 M1 成功
- `filled` 必须同时确认成交明细，才视为 M1 成功
- `submitted`、`pending_new`、`partially_filled` 等非终态，即使查到状态，也不视为成功

## 4. 数据模型

### 4.1 OrderRequest

表示一次手工交易请求：

- `symbol`
- `volume`
- `side`
- `price_type`
- `price`

### 4.2 OrderSubmitResult

表示柜台同步受理结果：

- `accepted`
- `cl_ord_id`
- `broker_order_id`
- `symbol`
- `message`
- `raw_status`
- `event_time`

### 4.3 OrderStatusSnapshot

表示一次查单快照：

- `cl_ord_id`
- `broker_order_id`
- `symbol`
- `status`
- `filled_volume`
- `remaining_volume`
- `rejection_reason`
- `event_time`

### 4.4 OrderExecutionSnapshot

表示一次查成交快照：

- `cl_ord_id`
- `broker_order_id`
- `symbol`
- `filled_volume`
- `avg_price`
- `event_time`

### 4.5 TradeReport

表示 M1 最终验证结果：

- `side`
- `submit_accepted`
- `order_status_confirmed`
- `execution_status_confirmed`
- `last_order_status`
- `rejection_reason`
- `filled_volume`
- `avg_price`
- `verification_passed`
- `message`

## 5. 服务设计

### 5.1 GMTradeQueryGateway

职责：

- 连接掘金运行环境
- 提交买单或卖单
- 按内部委托号查单
- 按内部委托号查成交

当前网关只暴露统一查询接口，不在主流程中承担任何异步处理职责。

### 5.2 ManualTradeService

职责：

1. 校验输入参数
2. 组装 `OrderRequest`
3. 调用 `submit_order()`
4. 在超时时间内轮询查询状态
5. 把查询结果转成内部事件
6. 消费内部事件，更新当前聚合状态
7. 生成 `TradeReport`

### 5.3 内部事件思想

M1 已按后续状态机方向做了最小实现：

- 一次查单结果会先变成内部订单事件
- 一次查成交结果会先变成内部成交事件
- 聚合器消费这些事件，得到当前订单视图

当前事件只在服务内存中使用；后续接入数据库时，这些事件会写入状态表消费链路。

## 6. 输出口径

CLI 当前输出字段：

```json
{
  "verification_passed": true,
  "side": "sell",
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

说明：

- CLI 只输出当前最需要核对的结构化字段
- `buy` 与 `sell` 共用一套输出结构
- 失败时仍输出同一结构，便于脚本消费和人工核对

## 7. 日志与审计

M1 至少记录以下事件：

- `m1_manual_trade_starting`
- `order_submit_request`
- `order_submit_result`
- `order_status_reconciled`
- `execution_status_reconciled`
- `m1_manual_trade_query_closed`
- `m1_manual_trade_timeout`
- `m1_manual_trade_failed`

## 8. 测试策略

### 8.1 单元测试

- 模型字段映射
- Gateway 买卖方向映射
- ManualTradeService `buy/sell` 成功场景
- ManualTradeService 非终态超时场景
- 报告字段输出契约

### 8.2 集成测试

- 使用假 SDK 串联 gateway 与 service
- 验证买单和卖单提交后都能通过查询确认终态
- 验证成交场景能拿到数量和均价

## 9. 后续扩展

M1 之后的推荐演进是：

1. 查询结果写成可持久化内部事件
2. 状态机消费事件并更新状态表
3. 定时与供应商结果对账

这样可以把“验证脚本”平滑扩展成“正式执行链路”。
