# 市场分析调度器运行说明

## 概述

市场分析调度器是一个独立的盘后分析系统，负责：
- 每日自动同步全市场日线数据到 MySQL
- 计算市场宽度、赚钱效应、容错、情绪等指标
- 生成最近 10 个交易日的分析报告
- 通过飞书 Webhook 推送日报

## 前置条件

### 1. 环境依赖

- Python 3.10+
- MySQL 5.7+ 或 MariaDB 10.3+
- 掘金终端（本地运行在 127.0.0.1:7001）

### 2. 安装依赖

```bash
pip install -e .
```

### 3. 配置文件

复制示例配置并修改：

```bash
cp config/sim_account.example.yaml config/sim_account.yaml
```

编辑 `config/sim_account.yaml`，设置以下环境变量或直接填写：

```yaml
gm:
  token: ${GM_TOKEN}              # 掘金 API Token
  endpoint: 127.0.0.1:7001        # 掘金终端地址
  timezone: Asia/Shanghai

trade:
  enabled: false                  # 自动交易默认关闭
  account_id: ${GM_ACCOUNT_ID}
  # ... 其他交易配置

market_analysis:
  enabled: true                   # 盘后分析默认开启
  universe: ashare_main_gem_star  # 沪深主板+创业板+科创板
  history_years: 3                # 首次回补 3 年数据
  recent_trade_days: 10           # 报告展示最近 10 个交易日
  report_time: "19:15"            # 每日 19:15 触发

mysql:
  host: 127.0.0.1
  port: 3306
  database: market_data
  user: ${MYSQL_USER}
  password: ${MYSQL_PASSWORD}

feishu:
  webhook: ${FEISHU_WEBHOOK}      # 飞书群机器人 Webhook

scheduler:
  enabled: true
  retry_interval_minutes: 10      # 失败后每 10 分钟重试
  max_attempts: 3                 # 最多重试 3 次

log_dir: logs
```

### 4. 数据库准备

创建数据库（如果不存在）：

```sql
CREATE DATABASE market_data CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

调度器首次运行时会自动创建表结构。

## 运行方式

### 方式 1：常驻调度器（推荐）

启动常驻调度器，每日 19:15 自动执行盘后任务：

```bash
python scheduler.py --config config/sim_account.yaml
```

### 方式 2：手动触发一次

手动触发一次盘后任务（用于测试或补数）：

```bash
python scheduler.py --config config/sim_account.yaml --once
```

## 数据同步逻辑

### 首次运行

- 回补近 3 年全市场日线数据
- 同步股票池（沪深主板 + 创业板 + 科创板）
- 更新 checkpoint 到最新交易日

### 后续运行

- 从上次成功同步的交易日开始增量补数
- 自动识别缺口（如电脑多天未开机）
- 只同步新增交易日数据

## 数据表结构

### market_security_master

股票池静态属性：

- `symbol`: 股票代码（主键）
- `exchange`: 交易所
- `name`: 股票名称
- `board`: 板块（main/gem/star）
- `listed_date`: 上市日期

### market_daily_bar

日线行情数据：

- `symbol + trade_date`: 联合主键
- `open/high/low/close/pre_close`: 价格
- `volume/amount`: 成交量/成交额
- `turnover_rate`: 换手率
- `is_st`: 是否 ST
- `suspended`: 是否停牌
- `has_trade`: 是否有成交

### market_sync_checkpoint

同步检查点：

- `job_name`: 任务名称（主键）
- `last_success_trade_date`: 最后成功同步日期
- `updated_at`: 更新时间

## 飞书消息格式

每日 19:15 发送的飞书消息包含：

1. **标题**：📊 市场分析日报 - YYYY-MM-DD
2. **摘要**：当日市场概况（上涨家数、下跌家数、上涨占比）
3. **明细表**：最近 10 个交易日逐日数据

## 日志文件

日志文件位于 `logs/` 目录：

- `market-analysis-scheduler_YYYYMMDD.log`: 调度器主日志
- 包含：数据同步进度、分析计算、飞书推送、错误信息

## 故障排查

### 1. 数据库连接失败

**错误**：`repository.connection_failed`

**解决**：
- 检查 MySQL 是否运行
- 确认 `mysql.user` 和 `mysql.password` 正确
- 确认数据库 `market_data` 已创建

### 2. 掘金 API 连接失败

**错误**：`gm.fetch_instruments_failed`

**解决**：
- 确认掘金终端正在运行
- 检查 `gm.endpoint` 是否为 `127.0.0.1:7001`
- 确认 `gm.token` 有效

### 3. 飞书消息发送失败

**错误**：`feishu.send_failed`

**解决**：
- 检查 `feishu.webhook` 是否正确
- 确认飞书群机器人已启用
- 检查网络连接

### 4. 首次同步时间过长

**原因**：首次回补 3 年全市场数据（约 5000 只股票 × 700 个交易日）

**建议**：
- 首次运行建议在非交易时段执行
- 预计耗时：30-60 分钟（取决于网络和数据库性能）
- 后续增量同步通常在 1-5 分钟内完成

## 与自动交易的关系

- `scheduler.py` 和 `main.py` 是两个独立入口
- `main.py` 仍然用于自动交易执行
- `scheduler.py` 只负责盘后分析和调度
- 两者可以同时运行，互不干扰

## 配置项说明

### market_analysis.report_time

- 默认 `19:15`（晚上 7:15）
- 原因：掘金官方日线数据通常在晚间更新
- 如果设置为 `15:15`，可能拿不到当日完整数据

### scheduler.max_attempts

- 默认 `3` 次
- 失败后每 `retry_interval_minutes` 分钟重试一次
- 达到最大次数后停止，等待下一个调度周期

### market_analysis.history_years

- 默认 `3` 年
- 只在首次同步时生效
- 后续运行始终增量补数

## 性能优化建议

1. **批量大小**：当前每批 50 只股票，可根据网络情况调整
2. **数据库索引**：已自动创建必要索引
3. **并发控制**：调度器设置 `max_instances=1`，避免重复执行

## 未来扩展

当前版本的分析器返回占位数据，完整指标计算逻辑待实现：

- `MarketBreadthAnalyzer`: 市场宽度指标
- `MarketProfitEffectAnalyzer`: 赚钱效应指标
- `MarketToleranceAnalyzer`: 容错指标
- `MarketEmotionAnalyzer`: 情绪指标

实现路径：
1. 从 MySQL 读取日线数据
2. 使用 pandas 进行向量化计算
3. 返回结构化指标结果
