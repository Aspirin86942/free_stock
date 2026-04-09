# M1 双向手工验证查询收口 Implementation Plan

> 本文件为历史 M1 实施计划的统一修订版，当前以查询驱动实现为准。

## Goal

实现 M1 里程碑：手工触发一笔 `buy/sell` 委托，提交委托，并通过查询确认最终状态，输出验证报告。

## Architecture

M1 在 M0 基础上增加四块能力：

1. 交易网关扩展：`submit_order()`、`query_order_status()`、`query_execution_reports()`
2. 手工验证服务：轮询查询并聚合订单结果
3. CLI 扩展：支持 `--mode m1 --side buy|sell`
4. 测试补齐：模型、网关、服务、启动层

主路径统一为：

```text
提交委托 -> 查单 -> 查成交 -> 内部事件 -> 聚合结果 -> 输出报告
```

## Planned Files

### Modified

- `src/gmtrade_live/models.py`
- `src/gmtrade_live/gateways/protocols.py`
- `src/gmtrade_live/gateways/gmtrade_trade_gateway.py`
- `src/gmtrade_live/services/m1_manual_trade.py`
- `src/gmtrade_live/bootstrap.py`
- `main.py`
- `tests/unit/test_models.py`
- `tests/unit/test_official_gateways.py`
- `tests/unit/test_m1_manual_trade.py`
- `tests/unit/test_bootstrap.py`
- `tests/integration/test_m1_manual_trade_service.py`

## Scope Guard

M1 只做：

- 手工触发一笔 `buy/sell` 委托
- 提交委托
- 查询订单状态
- 查询成交明细
- 生成结构化验证报告

M1 不做：

- 自动触发卖出
- 自动触发买入
- 卖出许可规则
- 防重复卖单完整策略
- 状态表
- 数据库

## Tasks

### Task 1: 扩展模型

- 收敛 `OrderRequest` 为通用手工交易请求
- 为 `TradeReport` 增加 `side`
- 保持所有金额字段继续使用 `Decimal`

### Task 2: 扩展交易网关

- 保留 M0 查询能力
- 增加买卖双向提交
- 增加按 `cl_ord_id` 查单
- 增加按 `cl_ord_id` 查成交
- 统一映射掘金状态码

### Task 3: 实现 ManualTradeService

- 校验 `side/symbol/volume/price_type/price/timeout_seconds`
- 提交委托
- 轮询查单
- 在需要时查成交
- 把查询结果转成内部事件
- 聚合生成最终报告

### Task 4: 接入 CLI 和 bootstrap

- `main.py` 增加 `--side buy|sell`
- `bootstrap.run_m1_manual_trade()` 透传方向并输出 JSON

### Task 5: 验证

运行：

```powershell
conda run -n stock_analysis pytest tests/unit/test_models.py tests/unit/test_official_gateways.py tests/unit/test_m1_manual_trade.py tests/unit/test_bootstrap.py -q
conda run -n stock_analysis pytest tests/integration/test_m1_manual_trade_service.py -q
conda run -n stock_analysis python main.py --config config/sim_account.yaml --mode m1 --side sell --symbol SHSE.600839 --volume 100 --price-type market --timeout-seconds 60
conda run -n stock_analysis python main.py --config config/sim_account.yaml --mode m1 --side buy --symbol SHSE.600839 --volume 100 --price-type limit --price 10.50 --timeout-seconds 120
```

## Acceptance

- `buy` 与 `sell` 委托提交后都能拿到同步结果
- 终态能通过查单确认
- 成交场景能通过查成交确认数量和均价
- 报告字段稳定、可脚本消费
- 非终态超时场景有明确失败信息
- 自动执行主线仍然只做自动卖出
