# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## 项目概述

东方财富掘金实盘执行系统（第一期）- 在掘金仿真账户中实现"持仓识别 -> 规则判断 -> 自动卖出 -> 回报收口 -> 日志审计"的最小闭环。

**核心约束**：
- 只做自动卖出，不做自动买入
- 单账户、单策略、统一参数
- Python 3.10+，单进程常驻
- 所有交易与行情统一走掘金官方接口
- 主干命名已完成去阶段化；正式入口、`services/` 文件名、测试名和文档口径不再使用旧阶段编号

## 开发命令

### 执行环境

- 默认使用 conda 环境：`stock_analysis`
- 安装、运行、测试、lint、格式化、类型检查，优先使用 `conda run -n stock_analysis ...`
- 非项目明确要求时，不混用系统 Python、其他 conda 环境或独立 `.venv`

### 安装与运行
```bash
# 安装项目（开发模式）
conda run -n stock_analysis python -m pip install -e .

# 自动卖出入口（需要先启动掘金终端）
conda run --no-capture-output -n stock_analysis python main.py --config config/sim_account.yaml
```

### 入口清单
```bash
# 自动卖出入口
conda run -n stock_analysis python main.py --config config/sim_account.yaml

# 决策观测入口
conda run -n stock_analysis python observe_decisions.py --config config/sim_account.yaml --once

# 调试连通性
conda run -n stock_analysis python tools/debug/check_connectivity.py --config config/sim_account.yaml

# 调试手工交易
conda run -n stock_analysis python tools/debug/manual_trade.py --config config/sim_account.yaml --side sell --symbol SHSE.600839 --volume 100 --price-type market --timeout-seconds 60
```

### 测试
```bash
# 运行所有测试
conda run -n stock_analysis pytest

# 运行单个测试文件
conda run -n stock_analysis pytest tests/unit/test_config.py

# 运行单个测试函数
conda run -n stock_analysis pytest tests/unit/test_config.py::test_load_config_success

# 集成测试（需要掘金终端运行）
conda run -n stock_analysis pytest tests/integration/
```

### 配置文件
- 示例配置：`config/sim_account.example.yaml`
- 实际配置：`config/sim_account.yaml`（已在 .gitignore 中）
- **关键配置项**：
  - `gmtrade_endpoint`: 必须是 `127.0.0.1:7001`（本地掘金终端），不是远程地址
  - `account_id` 和 `token`：从掘金终端获取
  - `sell_quantity_ratio`：每轮自动卖出的仓位比例，必须满足 `0 < ratio <= 1`

## 架构设计

### 四层架构

```
基础设施层 (app_runner.py, config.py, logging_setup.py, session.py)
  ├─ 配置加载、日志初始化、交易时段判断、正式入口编排
  │
数据接入层 (gateways/)
  ├─ GMTradeGateway: 账户资金、持仓查询
  ├─ GMCurrentQuoteGateway: 行情数据获取
  ├─ protocols.py: Gateway 接口定义
  │
共享评估层 (services/)
  ├─ SellCandidatePipeline: 拉持仓、拉行情、生成候选卖出标的
  ├─ SellDecisionEngine: 止盈止损判断、卖出许可判断
  ├─ PositionDecisionStateStore: 逐标的决策状态与墓碑状态
  ├─ DecisionObserverService: 只读观测输出
  │
交易执行层 (services/)
  ├─ AutoSellService: 卖单执行、委托跟踪、成交收口、防重复卖单
  ├─ SellQuantityPolicy: 卖量规划
  ├─ OrderExecutionStateStore: 执行状态机
```

### 架构约束（必须遵守）

1. **分层隔离**：所有外部交易与行情调用必须经过数据接入层（gateways/）
2. **职责分离**：核心决策层只负责"该不该卖"，不直接发单；交易执行层只负责"怎么卖"
3. **状态隔离**：状态必须按标的（symbol）隔离，禁止用单一全局布尔值
4. **不可变模型**：所有 dataclass 使用 `frozen=True, slots=True`（参考 models.py）
5. **命名回归禁止**：活跃文件与文件路径中禁止重新引入旧阶段编号；以 `tests/unit/test_stage_name_guard.py` 为门禁

### 关键模块

- **models.py**: 核心数据模型（CashSnapshot, PositionSnapshot, QuoteSnapshot）
- **precision.py**: 金额精度处理，所有金额必须用 `Decimal`，禁止 `float`
- **app_runner.py**: 正式自动卖出入口与正式决策观测入口的运行编排
- **sell_candidate_pipeline.py**: 共享评估管线，统一输出候选卖出标的与变化事件
- **position_decision_state.py**: 决策状态管理（watching / tombstone）
- **order_execution_state.py**: 执行状态管理（submitting / submitted / filled 等）
- **auto_sell_service.py**: 自动卖出执行编排
- **decision_observer.py**: 决策观测编排
- **session.py**: 交易时段判断（pre_open, in_session, post_close）
- **errors.py**: 自定义异常定义

## 数据处理规范

### 金额与精度
- 所有金额、价格、比例必须用 `decimal.Decimal`
- 禁止使用 `float` 进行金额计算
- 参考 `precision.py` 中的工具函数

### 错误处理
- 禁止静默失败（`try/except: pass`）
- 异常必须记录到日志（带 `account_id`、`symbol` 等上下文）
- 对外接口必须返回结构化错误（参考 `errors.py`）

### 日志规范
- 使用 `logging_setup.py` 初始化日志
- 关键操作必须记录：连接状态、持仓变化、委托发送、成交回报
- 日志格式：`{timestamp} {level} {strategy_name} {message} key1=value1 key2=value2`

## 测试策略

### 连通性验证
重点验证：
1. 掘金 API 连接正常
2. 能读取账户资金
3. 能读取持仓列表
4. 能获取行情数据

通过调试连通性工具验证（见上方入口清单）。

### 单元测试 vs 集成测试
- **单元测试**（tests/unit/）：不依赖掘金终端，使用 mock
- **集成测试**（tests/integration/）：需要掘金终端运行，测试真实 API 调用
- **调试脚本测试**（tests/debug/）：覆盖 `tools/debug` 下的连通性检查与手工交易脚本
- **命名门禁**：`tests/unit/test_stage_name_guard.py` 负责阻止阶段化命名重新回流到活跃文件

## 常见问题

### 运行时错误
1. **ModuleNotFoundError: No module named 'gmtrade_live'**
   - 解决：运行 `conda run -n stock_analysis python -m pip install -e .`

2. **GmError: 无法获取掘金服务器地址列表**
   - 原因：掘金终端未运行或 `gmtrade_endpoint` 配置错误
   - 解决：启动掘金终端，确认 `gmtrade_endpoint: 127.0.0.1:7001`

3. **usage: main.py [-h] --config CONFIG**
   - 原因：未指定配置文件
   - 解决：`conda run -n stock_analysis python main.py --config config/sim_account.yaml`

## 文档参考

- 运行说明：`docs/auto-sell-runtime.md`
- 系统规划书：`docs/Proposal/量化交易系统规划书.md`
- 分层 Spec：`docs/superpowers/specs/01-基础设施层-spec.md` 等
- 实施计划：`docs/superpowers/plans/`
