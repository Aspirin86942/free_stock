# 总入口收敛与盘后调度稳健性加固设计

日期：2026-04-21

## 1. 背景

当前项目存在两类入口与一组盘后链路稳定性问题：

1. 入口层面：`main.py`（自动交易）与 `scheduler.py`（调度）并列，使用成本与认知成本较高。
2. 调度层面：盘后任务触发语义偏“每日定时”，缺少“交易日完成态”硬约束，容易在周末/节假日重复触发。
3. 稳定性层面：空报告保护、异常资源释放、配置布尔解析安全等基础问题会放大重试链路噪音。
4. 指标层面：在仅 `gm + MySQL` 事实源约束下，部分口径可精确实现，部分只能近似实现，需要显式降级与审计说明。

用户在本阶段给出的硬约束：

- `trade job` 默认关闭，避免程序启动时误开交易。
- 即使手工配置 `trade.enabled=true`，本阶段也只做占位，不执行真实交易。
- 数据源仅允许 `gm + MySQL`，不引入第三方数据源。
- 入口整改为单入口：仅保留 `main.py`，删除 `scheduler.py`。
- `main.py` 采用子命令分发（`trade` / `scheduler`）。
- 盘后触发时间为 `19:15`（已确认不使用 `15:15`）。

## 2. 目标与非目标

### 2.1 目标

本次设计完成后应满足：

1. `main.py` 成为唯一入口，支持子命令分发。
2. `scheduler.py` 被移除，不再作为独立入口。
3. 调度链路在 `19:15` 触发时具备“交易日完成态”判定，避免非交易日无效执行。
4. 盘后任务失败重试保持“每 10 分钟一次，最多 3 次”，并区分“可跳过/可重试/不可重试”。
5. 报告发送幂等化：同一交易日不重复发送；有历史缺口只补数，不补发历史日报。
6. 在 `gm + MySQL` 约束下最大化补齐指标，并对受限指标显式降级与审计。
7. 补齐关键单测，覆盖入口分发、调度语义、幂等与降级行为。

### 2.2 非目标

1. 本阶段不实现 `trade job` 的真实调度执行。
2. 不引入第三方数据源用于 ST 历史状态或高级事件标签。
3. 不做大规模架构重写，仅做渐进式增强。

## 3. 方案对比与选择

### 方案 A：一次性重构

- 特点：大幅重写入口、调度、指标层。
- 风险：回归风险高，交付周期长。

### 方案 B：渐进增强（选中）

- 特点：保留现有模块边界，先修高风险运行问题，再补齐可实现指标。
- 优势：风险可控、验证路径清晰、能快速改善线上稳定性。

### 方案 C：仅修 bug

- 特点：只修调度/稳定性，不补指标口径。
- 缺点：无法满足本次“修复+完善”目标。

## 4. 总体架构

### 4.1 入口层

单入口 `main.py` 负责 CLI 分发，不承载业务逻辑：

- `main.py trade ...` -> 自动交易执行链路
- `main.py scheduler ...` -> 盘后调度链路
- （可选保留）`observe_decisions.py` 作为过渡入口，后续再收敛

`scheduler.py` 删除，避免双入口并行演进导致行为漂移。

### 4.2 调度层

`RuntimeScheduler` 继续作为调度编排器，核心增强：

1. 触发后先进行“交易日完成态”判定。
2. 判定为“未完成交易日/无可执行数据”时跳过，不进入失败重试。
3. 仅对可重试失败进入 10 分钟 * 3 次重试链。
4. `trade.enabled=true` 时仅输出占位告警，不执行交易任务。

### 4.3 任务层

`market_close_job` 仍负责闭环：

1. 补数（首次三年 + 增量缺口）
2. 基于 MySQL 生成最近 10 个交易日明细
3. 发送飞书
4. 推进发送 checkpoint（幂等）

并新增保证：

- 连接释放使用 `try/finally`
- 空报告安全处理
- 明确错误模型（retryable / non-retryable / skippable）

## 5. 数据与幂等语义

### 5.1 唯一事实源

盘后分析唯一事实源是 MySQL（`market_daily_bar`、`market_security_master`、`market_sync_checkpoint`）。

### 5.2 Checkpoint 语义

复用 `market_sync_checkpoint` 的 `job_name` 分区：

- `market_daily_sync`：最近一次成功同步交易日
- `market_close_report_sent`：最近一次成功发送日报交易日

### 5.3 幂等规则

1. 若 `market_close_report_sent == latest_completed_trade_date`，本轮跳过发送。
2. 若有历史缺口，仅补数并发送“最新已完成交易日”一条，不补发历史。
3. 发送成功后再推进 `market_close_report_sent`。

## 6. 指标完善策略（仅 gm + MySQL）

### 6.1 分级实现

1. A 级（高可实现）：上涨/下跌/占比、成交额、20/60 日新高新低、9.5% 突破计数、3 日 30% 计数。
2. B 级（规则近似）：涨跌停、连板、炸板、热门股均价与回撤相关指标。
3. C 级（数据源受限）：历史 ST 精确剔除等无法完全还原指标。

### 6.2 降级约束

1. 允许 `best-effort`，但必须显式输出 `data_quality_flags`。
2. 飞书消息底部添加简短口径说明。
3. 日志中记录降级原因、影响指标、交易日，禁止静默降级。

## 7. 错误模型与可观测性

### 7.1 错误分类

1. `skippable`：非交易日、数据未完成，不重试。
2. `retryable`：网络波动、临时数据库失败、飞书临时失败，进入重试链。
3. `non_retryable`：配置错误、参数非法，直接终止本轮。

### 7.2 日志上下文

关键日志至少包含：

- `job_name`
- `attempt`
- `latest_trade_date`
- `sent_trade_date`
- `retryable`
- `skip_reason`（如有）

## 8. 测试与验收

### 8.1 单元测试覆盖面

1. `main.py` 子命令分发：`trade/scheduler` 参数、互斥参数、错误参数。
2. `runtime_scheduler.py`：交易日判定、跳过语义、重试边界、trade 占位行为。
3. `market_close_job.py`：幂等发送、空报告保护、异常资源释放。
4. `config.py`：布尔安全解析（避免 `"false"` 被当作 `True`）。
5. 分析器：A/B/C 级指标与降级标记。

### 8.2 验收标准

1. 入口只保留 `main.py`。
2. `main.py scheduler` 在非交易日不触发发送且不进入失败重试。
3. 同一交易日重复触发不会重复发飞书。
4. `trade.enabled=true` 不会执行真实交易，仅有明确占位告警。
5. 报告可稳定输出最近 10 个交易日明细，空数据不崩溃。

## 9. 实施分批

### 批次 1（高风险修复）

1. 入口收敛：`main.py` 子命令化，移除 `scheduler.py`。
2. 调度修复：交易日完成态判定 + 跳过语义。
3. 稳定性修复：空报告保护、连接释放、布尔安全解析。
4. 测试补齐：入口分发、调度重试、幂等发送。

### 批次 2（指标完善）

1. 补齐 A/B 级指标计算逻辑。
2. C 级指标实现显式降级与审计。
3. 飞书模板补充口径说明与质量标记。

## 10. 伪代码草案

### 10.1 目标

说明单入口分发、调度判定、幂等发送、降级审计的主流程。

### 10.2 输入

- `argv`: CLI 输入参数
- `runtime_config`: 包含 `gm/trade/market_analysis/mysql/feishu/scheduler` 的运行配置
- `dependencies`: gateway/repository/analyzers/notifier/scheduler

### 10.3 输出

- 成功：任务状态、报告交易日、是否发送、影响行数
- 跳过：跳过原因（非交易日、数据未完成、重复发送）
- 失败：结构化错误（error_code、message、retryable）

### 10.4 伪代码草案

```python
# [伪代码草案]
# 目标：统一入口分发 trade/scheduler，并保证盘后任务在交易日完成态下稳健执行
# 输入：
# - argv: 命令行参数
# - runtime_config: 运行时配置
# - dependencies: 调度器、网关、仓储、分析器、通知器
# 输出：
# - success_result: 成功执行结果（含 report_trade_date、sent）
# - skip_result: 跳过结果（含 skip_reason）
# - error_result: 失败结果（含 retryable）

def main(argv, dependencies):
    # 1. 单入口分发：明确子命令边界，避免一个入口承载两套生命周期
    cmd = parse_subcommand(argv)
    if cmd.name == "trade":
        return run_trade_entry(cmd.args)
    if cmd.name == "scheduler":
        return run_scheduler_entry(cmd.args, dependencies)
    return build_error_result("INVALID_COMMAND", "不支持的子命令", retryable=False)


def run_scheduler_entry(args, dependencies):
    config = load_runtime_config(args.config)
    scheduler = build_scheduler(config.gm.timezone)

    # 2. trade job 占位：本阶段只允许占位，不执行真实交易
    if config.trade.enabled:
        log_warn("trade_job_enabled_but_unimplemented")

    if config.market_analysis.enabled:
        scheduler.add_job(
            id="market_close_job",
            trigger=cron_at(config.market_analysis.report_time),
            func=lambda: run_market_close_with_retry(config, dependencies),
        )

    if args.once:
        return run_market_close_with_retry(config, dependencies)

    scheduler.start()
    return build_success_result("SCHEDULER_STARTED")


def run_market_close_with_retry(config, dependencies):
    # 3. 可跳过场景优先判定：非交易日或数据未完成不应进入失败重试链
    if not is_trade_day_completed(config, dependencies.gateway):
        return build_skip_result("NO_COMPLETED_TRADE_DAY")

    max_attempts = config.scheduler.max_attempts
    for attempt in range(1, max_attempts + 1):
        try:
            result = run_market_close_once(config, dependencies)
            return result
        except RetryableError as exc:
            log_error("market_close_retryable_error", attempt=attempt, err=exc)
            if attempt >= max_attempts:
                return build_error_result("MARKET_CLOSE_RETRY_EXHAUSTED", str(exc), retryable=True)
            sleep_minutes(config.scheduler.retry_interval_minutes)
        except Exception as exc:
            # 4. 不可重试错误直接终止，避免盲目重复执行
            log_error("market_close_non_retryable_error", attempt=attempt, err=exc)
            return build_error_result("MARKET_CLOSE_FAILED", str(exc), retryable=False)


def run_market_close_once(config, dependencies):
    repository = dependencies.repository_factory(config.mysql)
    try:
        repository.connect()
        repository.ensure_tables()

        # 5. 先补数再分析：分析必须严格消费 MySQL 事实源
        sync_result = sync_market_data(config.market_analysis, dependencies.gateway, repository)
        latest_trade_date = sync_result.latest_trade_date

        # 6. 幂等发送：同一交易日已发送则直接跳过
        sent_date = repository.get_last_success_trade_date("market_close_report_sent")
        if sent_date == latest_trade_date:
            return build_skip_result("ALREADY_SENT")

        report = build_report_from_mysql(
            repository=repository,
            report_trade_date=latest_trade_date,
            recent_trade_days=config.market_analysis.recent_trade_days,
        )

        # 7. 空报告保护：避免 daily_rows[-1] 触发越界导致任务误失败
        if not report.daily_rows:
            return build_skip_result("EMPTY_REPORT_DATA")

        # 8. 降级透明化：受限口径必须带 quality flags 和日志审计
        report = attach_quality_flags(report)
        notify_feishu(config.feishu.webhook, report)
        repository.save_last_success_trade_date("market_close_report_sent", latest_trade_date)
        return build_success_result("MARKET_CLOSE_SENT", trade_date=latest_trade_date)
    finally:
        # 9. 资源兜底释放：无论成功失败都关闭连接，防止重试链路累积连接
        repository.close()
```

