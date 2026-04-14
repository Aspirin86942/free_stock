# Windows 本机调度与盘后市场分析设计

日期：2026-04-14

## 1. 背景

当前仓库的正式能力仍然集中在自动交易主链，核心前提是：

- 交易执行依赖本机掘金终端
- 官方行情读取同样依赖本机掘金端口
- 当前产品语义已经在向“交易主链与未来市场扩展边界隔离”收敛

基于这几个事实，本次新增的市场分析与飞书播报能力不适合部署到 Linux、群晖或其他独立主机，也不适合直接并回交易主入口。更稳妥的做法是：

- 继续全部部署在 Windows 本机
- 保留交易执行链路
- 新增独立的盘后市场分析链路
- 用统一的 `scheduler` 负责任务调度，而不是让一个大入口脚本同时承担所有职责

用户当前的明确目标是：

- 自动交易能力保留，但默认不自动开启
- 新增盘后分析能力，并在交易日 `15:15` 执行
- 盘后分析只做日线，不做分钟 K
- 行情分析需要基于“沪深主板 + 创业板 + 科创板”的全市场三年日 K
- 行情数据进入 MySQL 后再分析与推送
- 若电脑多天未开机，下次启动后要自动补齐缺失交易日
- 不补发历史飞书消息，但每次消息主体要覆盖最近 `10` 个交易日的逐日明细表

## 2. 目标与非目标

### 2.1 目标

本次设计完成后，系统应满足以下目标：

- 在 Windows 本机新增统一调度入口 `scheduler.py`
- `main.py` 仅保留自动交易执行入口，不承载盘后分析能力
- 调度器可统一编排 `trade job` 与 `market analysis job`
- `trade job` 默认关闭，避免程序启动时误开交易
- `market analysis job` 默认开启，并在交易日 `15:15` 触发
- 盘后任务支持失败后每 `10` 分钟重试一次，最多 `3` 次
- 首次运行回补近三年全市场日 K
- 后续运行按最近一次成功同步的交易日自动补齐缺失数据
- MySQL 作为盘后分析唯一事实源
- 飞书消息只发送最近一个已完成交易日的日报
- 日报主体展示最近 `10` 个交易日逐日明细表

### 2.2 非目标

本次设计不包含以下事项：

- 不修改现有自动交易策略本身
- 不修改交易执行链路中的止盈、止损、卖量规则
- 不把盘后分析链路并入自动交易主链
- 不把盘后分析任务部署到 Linux 或群晖
- 不实现分钟 K 入库
- 不新增分析结果表或报表仓库存档
- 不补发历史飞书消息
- 不把北交所纳入首版分析范围

## 3. 设计结论

### 3.1 运行边界

系统收敛为三类正式入口：

1. `main.py`
2. `scheduler.py`
3. 盘后分析内部任务入口 `market_close_job`

其中：

- `main.py` 只负责自动交易执行
- `scheduler.py` 只负责任务调度、失败重试和任务开关管理
- `market_close_job` 只负责盘后“补数 -> 分析 -> 飞书推送”闭环

### 3.2 调度语义

调度器统一管理两类任务：

- `trade job`
  - 保留
  - 默认关闭
  - 未来需要盘中自动开启时，由调度器显式开启
- `market analysis job`
  - 默认开启
  - 交易日 `15:15` 运行
  - 失败后每 `10` 分钟重试一次
  - 最多尝试 `3` 次

### 3.3 数据语义

盘后市场分析链路分为三段：

`官方历史行情拉取 -> MySQL 日线事实表 -> 分析与飞书投影`

这里的关键要求是：

- 只在同步成功后推进 checkpoint
- 只基于 MySQL 做盘后分析
- 不允许一边直接读取接口一边临时拼分析结果

### 3.4 消息语义

盘后分析消息遵循以下规则：

- 只发送最近一个已完成交易日的日报
- 若历史数据有缺口，只补数，不补发历史日报
- 飞书消息主体必须包含最近 `10` 个交易日逐日明细表
- 顶部可附加当天摘要，但摘要不能替代表格主体

## 4. 总体架构

### 4.1 自动交易主链

自动交易主链仍然维持既有语义：

`持仓读取 -> 行情读取 -> 决策状态同步 -> 卖出判定 -> 提交卖单 -> 查询收口 -> 审计输出`

本次只要求：

- 保留入口
- 后续可被调度器调起
- 默认不开启

### 4.2 盘后市场分析主链

盘后市场分析主链固定为：

`读取 checkpoint -> 补齐缺失日 K -> 读取 MySQL -> 生成最近10日表格 -> 发送飞书`

该主链的要求是：

- 分析结果必须来自库内完整数据
- 若补数失败，不允许继续对外发送
- 若发送失败，可按既定重试策略重跑整条盘后任务

### 4.3 配置分区

本次设计采用“一个 YAML 文件，多 section”的配置方式。物理上仍然是一个配置文件，但逻辑上拆分为多个配置块，避免交易链路、调度链路、MySQL 链路和飞书链路全部平铺在一个 dataclass 中。

建议结构如下：

```yaml
gm:
  token: ${GM_TOKEN}
  endpoint: 127.0.0.1:7001
  timezone: Asia/Shanghai

trade:
  enabled: false
  account_id: ${GM_ACCOUNT_ID}
  strategy_name: gmtrade-live-auto-sell
  poll_interval_seconds: 5
  take_profit_ratio: 0.015
  stop_loss_ratio: 0.02
  sell_quantity_ratio: 0.02
  market_session_mode: a_share

market_analysis:
  enabled: true
  universe: ashare_main_gem_star
  history_years: 3
  recent_trade_days: 10
  report_time: "15:15"

mysql:
  host: 127.0.0.1
  port: 3306
  database: market_data
  user: ${MYSQL_USER}
  password: ${MYSQL_PASSWORD}

feishu:
  webhook: ${FEISHU_WEBHOOK}

scheduler:
  enabled: true
  retry_interval_minutes: 10
  max_attempts: 3
```

该结构的核心含义是：

- `gm` 作为共享底座，供交易和盘后分析共用
- `trade` 只承载交易链路配置
- `market_analysis` 只承载盘后分析链路配置
- `scheduler` 只承载调度行为配置
- 交易账户信息不污染盘后分析链路

## 5. 数据模型与同步

### 5.1 数据表

首版只落 `3` 张核心表：

#### 5.1.1 `market_security_master`

作用：

- 提供股票池和静态属性
- 支撑市场范围过滤
- 支撑次新股过滤

至少包含以下字段：

- `symbol`
- `exchange`
- `name`
- `board`
- `listed_date`

#### 5.1.2 `market_daily_bar`

作用：

- 作为盘后分析唯一事实源

至少包含以下字段：

- `symbol`
- `trade_date`
- `open`
- `high`
- `low`
- `close`
- `pre_close`
- `volume`
- `amount`
- `turnover_rate`
- `is_st`
- `suspended`
- `has_trade`

约束：

- 以 `symbol + trade_date` 作为唯一键
- 采用 upsert 方式写入

#### 5.1.3 `market_sync_checkpoint`

作用：

- 记录同步成功推进到哪个交易日

至少包含以下字段：

- `job_name`
- `last_success_trade_date`
- `updated_at`

### 5.2 同步策略

同步必须区分首次运行和后续运行：

- 首次运行：
  回补近三年全量日 K
- 后续运行：
  从 `last_success_trade_date` 的下一交易日开始补
- 若电脑多天未开机：
  下次启动后自动补齐缺失交易日

### 5.3 Checkpoint 规则

checkpoint 必须遵循以下规则：

- 只有整次同步成功后才允许推进
- 部分批次失败时不得推进
- 发送飞书失败不影响已完成的行情同步 checkpoint
- 盘后分析与消息发送失败时，不得回滚已完成的行情同步结果

### 5.4 不落分析结果表

首版不落分析结果表，原因如下：

- 当前最重要的是先跑通口径和调度
- 最近 `10` 个交易日表格可运行时现算
- 若口径尚未稳定就落结果表，会引入回刷和版本迁移复杂度

## 6. 指标口径

### 6.1 统计范围

首版分析范围固定为：

- 沪深主板
- 创业板
- 科创板

不包含：

- 北交所

### 6.2 全局过滤规则

所有指标统一遵循以下过滤规则：

- 排除 `ST`
- 排除停牌
- 排除当日无成交股票

因此，任意指标中的“所有家数”默认指：

`统计范围内、非 ST、非停牌、当日有成交的股票数`

### 6.3 市场整体指标

首版保留以下整体指标：

- `上涨家数`
- `下跌家数`
- `上涨占比`
- `市场成交金额`
- `20日新高家数`
- `20日新低家数`
- `60日新高家数`
- `60日新低家数`

口径如下：

- `上涨家数`
  - `close > pre_close`
- `下跌家数`
  - `close < pre_close`
- `上涨占比`
  - `上涨家数 / 所有家数`
  - 这里“所有家数”包含上涨、下跌、平盘，只要满足全局过滤规则即可
- `市场成交金额`
  - 当日全市场成交额求和
- `20/60日新高家数`
  - 当日收盘价突破过去 `20/60` 个交易日窗口内的最高收盘价
- `20/60日新低家数`
  - 当日收盘价跌破过去 `20/60` 个交易日窗口内的最低收盘价

### 6.4 热门股定义

热门股必须满足以下条件：

- 非 `ST`
- 不属于次新股
- 昨日收盘价 `> 10`
- 昨日换手率 `> 10%`

其中：

- 次新股定义为上市 `250` 个交易日以内
- “股价 > 10”的判断基准明确为“昨日收盘价”，不是分析当日收盘价

### 6.5 赚钱效应指标

首版保留以下赚钱效应指标：

- `昨日涨停股今日平均收益`
- `昨日连板股今日平均收益`
- `热门股4日平均收益`

口径如下：

- `昨日涨停股今日平均收益`
  - 昨日真实涨停股票，在今日收盘相对昨日收盘的平均收益
- `昨日连板股今日平均收益`
  - 昨日已构成连续涨停的股票，在今日收盘相对昨日收盘的平均收益
- `热门股4日平均收益`
  - 以 `T-4` 收盘价为基准，到 `T` 收盘的平均收益

### 6.6 容错指标

首版保留以下容错指标：

- `昨日炸板股今日平均收益`
- `热门股收盘高于当日均价占比`
- `热门股日内最大回撤中位数`

口径如下：

- `昨日炸板股今日平均收益`
  - 昨日盘中触及真实涨停价，但收盘未封住的股票，在今日收盘相对昨日收盘的平均收益
- `热门股收盘高于当日均价占比`
  - 当日热门股中，`close > avg_price` 的股票数占比
  - 首版允许近似算法：`avg_price ≈ amount / volume`
- `热门股日内最大回撤中位数`
  - 当日热门股中，`(high - close) / high` 的中位数

### 6.7 情绪指标

首版保留以下情绪指标：

- `涨幅突破9.5家数`
- `跌幅突破9.5家数`
- `炸板率`
- `最近3日涨幅>30%家数`

口径如下：

- `涨幅突破9.5家数`
  - `pct_change > 9.5%`
- `跌幅突破9.5家数`
  - `pct_change < -9.5%`
- `炸板率`
  - `昨日盘中触及真实涨停价但收盘未封住的股票数 / 昨日盘中触及真实涨停价的股票数`
- `最近3日涨幅>30%家数`
  - 最近 `3` 个交易日累计涨幅大于 `30%` 的股票数量

### 6.8 真实涨停语义与近似情绪语义分离

必须严格区分两类口径：

- 真实涨停语义
  - 用于 `昨日涨停股`
  - 用于 `昨日炸板股`
  - 用于 `连板股`
- 近似情绪语义
  - 用于 `涨幅突破9.5家数`
  - 用于 `跌幅突破9.5家数`

两类口径不得混用，也不得以 `pct_change > 9.5%` 近似真实涨停判断。

## 7. 分析模块拆分

### 7.1 `MarketBreadthAnalyzer`

负责：

- `上涨家数`
- `下跌家数`
- `上涨占比`
- `市场成交金额`
- `20/60日新高家数`
- `20/60日新低家数`

### 7.2 `ProfitEffectAnalyzer`

负责：

- `昨日涨停股今日平均收益`
- `昨日连板股今日平均收益`
- `热门股4日平均收益`

### 7.3 `ToleranceAnalyzer`

负责：

- `昨日炸板股今日平均收益`
- `热门股收盘高于当日均价占比`
- `热门股日内最大回撤中位数`

### 7.4 `EmotionAnalyzer`

负责：

- `涨幅突破9.5家数`
- `跌幅突破9.5家数`
- `炸板率`
- `最近3日涨幅>30%家数`

### 7.5 `MarketCloseReportBuilder`

负责：

- 读取最近 `10` 个交易日结果
- 拼装逐日明细表
- 生成当天摘要
- 生成飞书投影载体

该模块不直接写指标口径，只消费 analyzer 输出。

## 8. 飞书输出结构

### 8.1 消息结构

首版飞书日报分为三段：

1. 标题
2. 当天摘要
3. 最近 `10` 个交易日逐日明细表

### 8.2 明细表列

建议首版明细表列顺序如下：

- `交易日`
- `上涨家数`
- `下跌家数`
- `上涨占比`
- `市场成交金额`
- `20日新高家数`
- `20日新低家数`
- `60日新高家数`
- `60日新低家数`
- `昨日涨停股今日平均收益`
- `昨日连板股今日平均收益`
- `热门股4日平均收益`
- `昨日炸板股今日平均收益`
- `热门股收盘高于当日均价占比`
- `热门股日内最大回撤中位数`
- `涨幅突破9.5家数`
- `跌幅突破9.5家数`
- `炸板率`
- `最近3日涨幅>30%家数`

### 8.3 历史消息策略

必须遵循以下规则：

- 不补发历史日报
- 只发最近一个已完成交易日
- 即使当天是补数后第一次成功运行，也只发当前最新交易日的日报

## 9. 伪代码草案

### 9.1 目标

- 用 `scheduler` 统一调度交易任务与盘后分析任务
- 让盘后分析基于 MySQL 日线事实表运行
- 支持首次三年全量回补、缺口补数、最近 `10` 个交易日逐日明细表和飞书推送

### 9.2 输入

- `config`: 单一 YAML，多 section，包含 `gm`、`trade`、`market_analysis`、`mysql`、`feishu`、`scheduler`
- `runtime_context`: 当前运行上下文，例如当前时间、交易日、重试次数
- `dependencies`: 交易运行器、历史行情网关、MySQL 仓储、分析器集合、飞书通知服务

### 9.3 输出

- `scheduler_runtime`: 常驻调度器实例
- `sync_result`: 行情同步结果，至少包含 `latest_trade_date`、`inserted_rows`、`updated_rows`
- `report_payload`: 盘后分析结果，包含 `summary` 和 `daily_rows`
- `job_success_result`: 成功任务结果，至少包含 `job_name`、`trade_date`、`attempt`
- `error_result`: 失败时的结构化错误，至少包含 `error_code`、`message`、`retryable`

### 9.4 伪代码草案

```python
def run_scheduler(config, dependencies):
    # 1. 调度器只做编排，不直接承载交易或分析逻辑，
    # 这样后续扩展任务时不会把入口脚本变成新的巨石文件。
    scheduler = build_scheduler(timezone=config.gm.timezone)

    # 2. 自动交易任务默认关闭，避免程序一启动就误开真实执行链路。
    if config.trade.enabled:
        scheduler.add_job(
            name="trade_job",
            trigger=build_trade_trigger(config.trade),
            func=lambda: run_trade_job(config, dependencies.trade_runner),
        )

    # 3. 盘后分析任务默认开启，固定在交易日 15:15 触发。
    if config.market_analysis.enabled:
        scheduler.add_job(
            name="market_close_job",
            trigger=build_market_close_trigger(config.market_analysis.report_time),
            func=lambda: run_market_close_job_with_retry(
                config=config,
                runtime_context=current_runtime_context(),
                dependencies=dependencies,
            ),
        )

    scheduler.start()
    return scheduler


def run_market_close_job_with_retry(config, runtime_context, dependencies):
    last_error = None

    # 4. 失败按固定策略重试，而不是无限重试，
    # 避免盘后任务因为外部依赖故障长期占住进程。
    for attempt in range(1, config.scheduler.max_attempts + 1):
        try:
            sync_result = sync_market_daily_bars(
                config=config,
                gateway=dependencies.historical_market_gateway,
                repository=dependencies.market_daily_repository,
                checkpoint_store=dependencies.checkpoint_store,
                calendar=dependencies.trade_calendar,
            )

            report_payload = build_market_close_report(
                report_trade_date=sync_result.latest_trade_date,
                recent_trade_days=config.market_analysis.recent_trade_days,
                repositories=dependencies.repositories,
                analyzers=dependencies.analyzers,
            )

            dependencies.feishu_notification_service.send_market_close_report(
                report_payload
            )

            return build_job_success_result(
                job_name="market_close_job",
                trade_date=sync_result.latest_trade_date,
                attempt=attempt,
            )

        except Exception as exc:
            last_error = exc
            log_market_close_error(exc, attempt=attempt)

            if attempt >= config.scheduler.max_attempts:
                break

            sleep_minutes(config.scheduler.retry_interval_minutes)

    return build_error_result(
        error_code="market_close_job_failed",
        message=str(last_error),
        retryable=True,
    )


def sync_market_daily_bars(config, gateway, repository, checkpoint_store, calendar):
    # 5. 首次运行做三年全量，后续只按 checkpoint 补缺口，
    # 这样既能支持历史初始化，也能覆盖电脑多天未开机的场景。
    last_success_trade_date = checkpoint_store.get_last_success_trade_date(
        "market_daily_sync"
    )

    if last_success_trade_date is None:
        start_trade_date = calendar.trade_date_n_years_ago(
            years=config.market_analysis.history_years
        )
    else:
        start_trade_date = calendar.next_trade_date(last_success_trade_date)

    end_trade_date = calendar.latest_completed_trade_date()

    if start_trade_date > end_trade_date:
        return build_sync_result(latest_trade_date=last_success_trade_date)

    securities = gateway.get_security_master(
        scope=config.market_analysis.universe
    )
    repository.upsert_security_master(securities)

    for batch_symbols in chunk_symbols(securities):
        rows = gateway.fetch_daily_bars(
            symbols=batch_symbols,
            start_trade_date=start_trade_date,
            end_trade_date=end_trade_date,
        )
        normalized_rows = normalize_daily_bar_rows(rows)
        repository.upsert_daily_bars(normalized_rows)

    # 6. 只有整批成功后才推进 checkpoint，
    # 避免出现“数据没有补全，但状态已前移”的审计缺口。
    checkpoint_store.save_last_success_trade_date(
        job_name="market_daily_sync",
        trade_date=end_trade_date,
    )

    return build_sync_result(latest_trade_date=end_trade_date)


def build_market_close_report(report_trade_date, recent_trade_days, repositories, analyzers):
    # 7. 报告只消费库内事实，不直接读接口，
    # 这样可以保证重试、多次运行和测试环境的行为一致。
    trade_dates = repositories.get_recent_trade_dates(
        end_date=report_trade_date,
        limit=recent_trade_days,
    )

    daily_rows = []
    for trade_date in trade_dates:
        breadth = analyzers.breadth.calculate(trade_date)
        profit = analyzers.profit_effect.calculate(trade_date)
        tolerance = analyzers.tolerance.calculate(trade_date)
        emotion = analyzers.emotion.calculate(trade_date)

        daily_rows.append(
            build_daily_report_row(
                trade_date=trade_date,
                breadth=breadth,
                profit=profit,
                tolerance=tolerance,
                emotion=emotion,
            )
        )

    summary = build_summary(
        latest_row=daily_rows[-1],
        previous_rows=daily_rows[:-1],
    )

    return build_report_payload(
        report_trade_date=report_trade_date,
        summary=summary,
        daily_rows=daily_rows,
    )
```

## 10. 风险点与边界条件

### 10.1 历史 `ST` 状态精度

若历史数据源无法稳定提供按交易日回溯的 `ST` 状态，则“所有指标排除 ST”在历史回溯场景下会存在精度风险。实现时必须明确这一点，不能默默降级后不记录。

### 10.2 换手率字段可得性

热门股定义依赖 `昨日换手率 > 10%`。若官方历史日线接口无法稳定提供换手率，盘后分析链路必须显式报错或引入可验证的补充来源，不能静默跳过。

### 10.3 连板与炸板识别

`昨日连板股` 与 `昨日炸板股` 依赖真实涨停识别。若只用涨跌幅近似，结论会系统性失真，因此该部分必须单独测试。

### 10.4 停牌与无成交

用户要求停牌或当日无成交股票不参与任何指标，因此同步层必须显式标记 `has_trade` / `suspended`，分析层不能靠 `volume == 0` 做隐式猜测后静默吞掉异常。

### 10.5 调度失败与重复发送

盘后任务支持自动重试，但必须保证：

- 同一个交易日只发送一条最终成功消息
- 同一重试链路中不能重复发送多条日报
- 若消息发送失败但数据同步已成功，不得重复回补同一批数据后错误推进其他状态

## 11. 验收要点

完成后的实现至少应满足以下验收标准：

- `main.py` 不承载盘后分析逻辑
- 新增 `scheduler.py` 可管理 `trade job` 与 `market analysis job`
- `trade job` 默认关闭，`market analysis job` 默认开启
- 盘后任务可在 `15:15` 触发，并支持失败后每 `10` 分钟重试一次，最多 `3` 次
- 首次运行可完成三年全量日 K 回补
- 电脑多天未开机时，下次运行可自动补齐缺失交易日
- 所有分析都基于 MySQL，不直接混用接口实时结果
- 飞书消息只发送最近一个已完成交易日，不补发历史消息
- 飞书消息主体包含最近 `10` 个交易日逐日明细表
