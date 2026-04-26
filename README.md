# 东方财富掘金实盘执行系统（free_stock）

> 面向协作者的仓库上手入口。第一次进入仓库先看这里；开始开发前请查阅仓库协作规范文档（`CONTRIBUTING.md`，若当前分支尚未提供请先向维护者确认）。

## 项目概览

本仓库当前包含两条独立但共享基础设施的链路：

### 1. 自动交易链路（`main.py trade`）

- 目标：在掘金仿真账户中完成“持仓识别 -> 规则判断 -> 自动卖出 -> 回报收口 -> 日志审计”的最小闭环
- 当前约束：只做自动卖出，不做自动买入
- 入口：`conda run -n stock_analysis python main.py trade --config config/sim_account.yaml`

### 2. 市场分析链路（`main.py scheduler`）

- 目标：完成“官方日线补数 -> MySQL -> 最近 10 个交易日盘后分析 -> 飞书推送”的完整链路
- 当前约束：依赖本地掘金终端、MySQL 和飞书 webhook
- 入口：`conda run -n stock_analysis python main.py scheduler --config config/sim_account.yaml --once`

## 开发环境与外部依赖

- Python `3.10+`
- conda 环境：`stock_analysis`
- 掘金终端：本地 `127.0.0.1:7001`
- MySQL：市场分析链路需要
- 飞书 webhook：盘后日报发送需要

> 注意：
> - `config/sim_account.yaml` 是本地私有配置，不可提交
> - `gm.token`、MySQL 密码、飞书 webhook 不要出现在 PR、issue、截图或录屏里
> - `tests/debug/` 包含调试相关测试；其中带 `real_env_debug` 标记的用例默认不会进入常规 `pytest` 回归，需显式指定 `tests/debug` 路径运行

## 快速开始

1. 安装项目

```bash
conda run -n stock_analysis python -m pip install -e .
```

2. 准备本地配置

- 参考 `config/sim_account.example.yaml` 新建 `config/sim_account.yaml`
- 至少填写 `gm`、`trade`、`market_analysis`、`mysql`、`feishu`、`scheduler`

3. 验证 CLI 可用

```bash
conda run -n stock_analysis python main.py -h
```

4. 运行一个安全的单元测试

```bash
conda run -n stock_analysis pytest tests/unit/test_config.py -q
```

## 常用命令

### 本地安全命令（不触达真实外部系统）

```bash
conda run -n stock_analysis python main.py -h
conda run -n stock_analysis pytest tests/unit/test_config.py -q
conda run -n stock_analysis pytest
```

### 只读或低风险调试（会连接真实服务，但不自动卖出）

```bash
conda run -n stock_analysis python observe_decisions.py --config config/sim_account.yaml --once
conda run -n stock_analysis python tools/debug/check_connectivity.py --config config/sim_account.yaml
conda run -n stock_analysis pytest tests/debug/test_market_close_report_preview.py -s
```

### 会写数据库或发送外部消息

```bash
conda run -n stock_analysis python main.py scheduler --config config/sim_account.yaml --once
```

### 可能触发真实交易指令

```bash
conda run -n stock_analysis python main.py trade --config config/sim_account.yaml
conda run -n stock_analysis python tools/debug/manual_trade.py --config config/sim_account.yaml --side sell --symbol SHSE.600839 --volume 100 --price-type market --timeout-seconds 60
```

## 项目结构

```text
src/gmtrade_live/          核心业务代码
tests/unit/                默认单元测试
tests/integration/         跨模块集成测试
tests/debug/               调试相关测试目录（带 `real_env_debug` 标记的用例默认不进入常规 pytest 回归）
tools/debug/               手工排障脚本
config/                    配置示例与本地配置入口
docs/                      运行说明、设计 spec、实现 plan
```

## 协作流程摘要

以下为目标协作约定（启用前提：由维护者先创建并维护 `dev` 分支）：

1. 从最新 `dev` 创建 `feature/*`、`fix/*`、`docs/*` 或 `refactor/*`
2. 在功能分支完成代码、测试和文档同步
3. 提 PR 回 `dev`
4. 合并方式统一使用 `Squash and merge`
5. `dev` 稳定后，再由维护者发起 `dev -> main` 的 PR

完整协作规则以仓库协作规范文档（`CONTRIBUTING.md`）为准；若当前快照尚未提供该文件，请先按维护者通知执行。

## 文档索引

- 自动交易运行说明：[`docs/auto-sell-runtime.md`](docs/auto-sell-runtime.md)
- 市场分析运行说明：[`docs/market-analysis-runtime.md`](docs/market-analysis-runtime.md)
- 系统规划书：[`docs/Proposal/量化交易系统规划书.md`](docs/Proposal/量化交易系统规划书.md)
- 设计 spec：[`docs/superpowers/specs/`](docs/superpowers/specs/)
- 实现 plan：[`docs/superpowers/plans/`](docs/superpowers/plans/)

## 注意事项

- 默认 conda 环境统一写 `stock_analysis`，不要在公共文档里混用其他环境名
- `main` 不是日常开发分支；若仓库已启用 `dev`，日常协作按 `dev -> feature/* -> PR -> dev` 执行
- 真实环境命令执行前，先确认它会不会发单、写数据库或发送飞书消息
- 修改命令、配置、流程或外部依赖口径时，记得同步更新文档
