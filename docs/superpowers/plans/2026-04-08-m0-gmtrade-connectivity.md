# GMTrade M0 环境与账户连通 Implementation Plan

> 本文件已按最新查询驱动架构修订。

## Goal

建立 `M0` 基线：程序能够启动、加载配置、连接东方财富掘金官方接口，并读取账户资金、持仓和当前持仓标的行情。

## Architecture

M0 只落地基础设施与查询能力：

- 配置加载与校验
- 日志初始化
- 交易时段判断
- `gm.api` 账户与持仓查询适配
- `gm.api.current` 行情查询适配
- 一条可验证的命令行检查路径

M0 不实现交易提交，也不实现订单状态收口。

## Deliverables

- `main.py`
- `src/gmtrade_live/config.py`
- `src/gmtrade_live/logging_setup.py`
- `src/gmtrade_live/session.py`
- `src/gmtrade_live/models.py`
- `src/gmtrade_live/precision.py`
- `src/gmtrade_live/gateways/gmtrade_trade_gateway.py`
- `src/gmtrade_live/gateways/gm_market_gateway.py`
- `src/gmtrade_live/services/m0_connectivity.py`
- `src/gmtrade_live/bootstrap.py`
- 对应单元测试与集成测试

## Scope Guard

M0 必须交付：

- 程序启动
- 配置校验
- 本地日志创建
- 交易时段计算
- 官方接口连通
- 账户资金读取
- 持仓读取
- 持仓标的行情读取

M0 不交付：

- 自动卖出
- 委托提交
- 查单
- 查成交
- 状态机

## Tasks

### Task 1: 建立项目骨架

- 建立 `pyproject.toml`
- 建立 `main.py`
- 建立包目录
- 建立基础测试入口

### Task 2: 完成基础设施能力

- 配置加载与校验
- 日志初始化
- 交易时段判断
- 统一错误模型
- 金额与价格精度归一

### Task 3: 完成官方查询网关

- 账户资金映射
- 持仓映射
- 行情映射
- 结构化错误处理

### Task 4: 完成 M0 服务与启动拼装

- `ConnectivityCheckService`
- `bootstrap.run_m0_connectivity_check`
- CLI 输出 JSON 摘要

### Task 5: 验证

运行：

```powershell
conda run -n stock_analysis pytest tests/unit/ -q
conda run -n stock_analysis pytest tests/integration/test_m0_connectivity_service.py -q
conda run -n stock_analysis python main.py --config config/sim_account.yaml
```

## Acceptance

- 能输出账户摘要 JSON
- 持仓为空时不报错
- 所有金额和价格使用 `Decimal` 归一
- 查询失败能输出结构化错误
