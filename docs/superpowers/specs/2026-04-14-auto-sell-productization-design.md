# 自动卖出系统去阶段化与产品化命名设计

日期：2026-04-14

## 1. 背景

当前仓库仍以 `M0`、`M1`、`M2`、`M3`、`M4` 作为主命名语义：

- CLI 入口通过 `--mode m0/m1/m2/m3` 切换能力
- 服务模块、类名、测试文件、日志事件均大量带有阶段编号
- `M4` 在当前实现中并不是运行模式，而是 smoke / 验收收口语义

这种命名方式在研发阶段可接受，但在一期系统即将闭环时已经不适合作为产品语义。最终交付物的真实定位是：

- 一个可持续轮询的自动卖出系统
- 能维护按标的的决策状态与执行状态
- 能对真实卖单进行提交、轮询、收口与审计
- 具备独立的观测入口与调试工具

因此，本次设计目标不是“再做一个新阶段”，而是把现有阶段化实现收敛成稳定、真实、可维护的产品命名与边界。

## 2. 目标与非目标

### 2.1 目标

本次重构完成后，主干产品语义应满足：

- 对外主入口不再暴露 `M0~M4`
- 内部模块名、类名、日志事件名、测试名、文档名、示例配置名全部去阶段化
- 正式产品只保留一个自动卖出入口
- 保留一个正式的决策观测入口，但其职责仅为观测，不参与发单
- `M0` 与 `M1` 能力不再进入正式产品入口，改为 `tools/debug` 下的调试脚本
- `M4` 不再作为任何运行能力命名，只保留为历史研发背景；主表达统一改为 smoke / acceptance / release-check 语义
- 自动卖出主链与未来市场扩展能力在架构层明确隔离

### 2.2 非目标

本次设计不包含以下事项：

- 不修改止盈止损策略本身
- 不修改卖量归一化规则本身
- 不把观测入口升级成发单入口
- 不引入新的买入能力
- 不在本次实现“三年日 K、市场广度、领涨领跌、飞书推送”等市场扩展能力，只保留明确的未来扩展边界

## 3. 设计结论

### 3.1 正式产品边界

系统收敛为四类能力：

1. 正式自动卖出入口
2. 正式决策观测入口
3. `tools/debug` 调试工具
4. smoke / acceptance / audit 质量与交付资产

其中：

- 自动卖出入口负责真实交易执行闭环
- 决策观测入口负责观察决策状态与候选卖出信号
- 调试工具仅服务于连通性验证、手工下单和排障
- 质量资产负责回归、smoke、日志审计与交付证明

### 3.2 自动卖出主链与未来市场扩展边界隔离

系统当前只收敛两类正式运行能力：

- 自动卖出主链：小范围、低延迟、强确定性
- 决策观测主链：围绕当前持仓的观测与变化输出

未来若新增“三年日 K、市场广度、领涨领跌、飞书推送”等市场扩展能力，必须作为独立扩展模块接入，不能直接并入当前交易主链或观测主链。若未来自动卖出需要读取市场状态，也只能通过显式输入边界对接，而不是让扩展逻辑反向污染交易链。

## 4. 正式产品架构

### 4.1 自动卖出主链

自动卖出主链负责以下流程：

`持仓读取 -> 行情读取 -> 决策状态同步 -> 卖出判定 -> 卖量规划 -> 提交卖单 -> 查询收口 -> 审计输出`

该主链的要求是：

- 轮询频率稳定
- 决策过程确定
- 订单执行可审计
- 单轮异常直接退出，避免在不确定状态下继续发单

### 4.2 决策观测主链

决策观测主链负责以下流程：

`持仓读取 -> 行情读取 -> 决策状态同步 -> 卖出判定 -> 输出变化与摘要`

该主链的要求是：

- 永不发单
- 输出结构化的轮次摘要与变化详情
- 允许单轮失败后记录错误并按既有策略继续后续轮次

### 4.3 未来市场扩展边界（本次不实现）

未来可能出现的市场扩展能力，典型流程如下：

`股票池/指数池 -> 历史行情装载 -> 市场结构计算 -> 生成 MarketContext -> 对外通知/投影`

该能力未来可能服务于：

- 飞书播报
- 市场领涨领跌统计
- 市场广度、情绪、风格状态计算
- 自动卖出策略的外部上下文输入

但本次不实现这部分能力，也不在本次代码结构中引入对应正式模块，只要求命名与分层上不要为未来扩展制造耦合障碍。

### 4.4 重构后的伪代码结构

以下伪代码只用于表达重构后的职责分层、复用关系和控制流，不等同于最终实现细节。

#### 4.4.1 共享评估管线 `SellCandidatePipeline`

```python
class SellCandidatePipeline:
    def evaluate_round(self, *, config: AppConfig, now: datetime) -> CandidateRound:
        session_state = resolve_trading_session(
            now,
            timezone_name=config.timezone,
            market_session_mode=config.market_session_mode,
        )

        positions = tuple(
            position
            for position in trade_gateway.get_positions(config.account_id)
            if position.volume > 0
        )

        decision_state_store.sync_positions(positions=positions, now=now)

        symbols = [position.symbol for position in positions]
        quotes = tuple(market_gateway.get_quotes(symbols)) if symbols else ()
        quote_map = {quote.symbol: quote for quote in quotes}

        evaluated_candidates: list[SellCandidate] = []
        change_events: list[DecisionChangeEvent] = []

        for position in positions:
            state = decision_state_store.get_state(position.symbol)
            if state is None:
                continue

            decision = decision_engine.evaluate(
                position=position,
                quote=quote_map.get(position.symbol),
                session_state=session_state,
                state_snapshot=state,
                config=config,
                now=now,
            )

            updated_state = decision_state_store.update_decision_feedback(
                position.symbol,
                trigger_reason=decision.trigger_reason,
                block_reason=decision.block_reason,
                volume=decision.volume,
                available_volume=decision.available_volume,
                sellable_now=decision.sellable_now,
                decision_time=decision.evaluated_at,
            )

            candidate = SellCandidate(
                position=position,
                quote=quote_map.get(position.symbol),
                decision=decision,
                decision_state=updated_state,
            )
            evaluated_candidates.append(candidate)

            change_events.extend(
                decision_change_detector.compare(
                    symbol=position.symbol,
                    current_decision=decision,
                    current_state=updated_state,
                )
            )

        return CandidateRound(
            session_state=session_state,
            positions=positions,
            candidates=tuple(evaluated_candidates),
            change_events=tuple(change_events),
        )
```

这个共享评估管线只负责：

- 拉持仓
- 拉行情
- 同步决策状态
- 调用卖出判定
- 产出候选结果与变化事件

它不负责：

- 发单
- 查单
- 成交回报收口
- 对外日志格式投影

#### 4.4.2 决策观测入口 `DecisionObserverService`

```python
class DecisionObserverService:
    def run_round(self, *, config: AppConfig, round_no: int) -> DecisionObservationReport:
        started_at = timer()
        now = clock()

        candidate_round = candidate_pipeline.evaluate_round(
            config=config,
            now=now,
        )

        return DecisionObservationReport(
            summary=build_decision_summary(
                round_no=round_no,
                session_state=candidate_round.session_state,
                candidates=candidate_round.candidates,
                change_events=candidate_round.change_events,
                duration_ms=elapsed_ms(started_at, timer()),
            ),
            change_events=candidate_round.change_events,
        )
```

```python
def run_decision_observer(config_path: Path, once: bool, max_rounds: int | None) -> int:
    config = load_config(config_path)
    connect_gateways_for_observer(config)

    round_no = 1
    while True:
        log_round_started(entry="decision_observer", round_no=round_no)
        try:
            report = decision_observer.run_round(config=config, round_no=round_no)
        except Exception as exc:
            emit_decision_round_error(round_no=round_no, exc=exc)
            if once or reached_max_rounds(round_no, max_rounds):
                return 1
        else:
            emit_decision_round_summary(report.summary)
            emit_decision_change_details(report.change_events)
            if once or reached_max_rounds(round_no, max_rounds):
                return 0

        sleep(config.poll_interval_seconds)
        round_no += 1
```

决策观测入口的关键语义：

- 复用共享评估管线
- 只投影观测摘要和变化详情
- 不允许发单
- 单轮异常按既有观测语义记录并决定是否继续下一轮

#### 4.4.3 自动卖出入口 `AutoSellService`

```python
class AutoSellService:
    def run_round(
        self,
        *,
        config: AppConfig,
        round_no: int,
        reconcile_timeout_seconds: int,
    ) -> AutoSellRoundReport:
        started_at = timer()
        now = clock()

        candidate_round = candidate_pipeline.evaluate_round(
            config=config,
            now=now,
        )

        block_details: list[SellBlockDetail] = []
        execution_details: list[SellExecutionDetail] = []
        tracked_symbols: dict[str, PositionSnapshot] = {}

        for candidate in candidate_round.candidates:
            if not candidate.decision.can_submit_sell:
                continue

            if order_execution_state_store.has_open_order(candidate.position.symbol):
                tracked_symbols[candidate.position.symbol] = candidate.position
                continue

            quantity_plan = sell_quantity_policy.plan(
                symbol=candidate.position.symbol,
                total_volume=candidate.position.volume,
                available_volume=candidate.position.available_volume,
                sell_quantity_ratio=config.sell_quantity_ratio,
            )

            if quantity_plan.block_reason is not None:
                block_details.append(
                    build_sell_block_detail(candidate, quantity_plan)
                )
                continue

            accepted, immediate_detail = submit_new_order(
                candidate=candidate,
                requested_volume=quantity_plan.final_target_volume,
                round_no=round_no,
                account_id=config.account_id,
            )

            if immediate_detail is not None:
                execution_details.append(immediate_detail)
                continue

            if accepted:
                tracked_symbols[candidate.position.symbol] = candidate.position

        execution_details.extend(
            reconcile_open_orders(
                tracked_symbols=tracked_symbols,
                reconcile_timeout_seconds=reconcile_timeout_seconds,
                round_no=round_no,
                account_id=config.account_id,
            )
        )

        return AutoSellRoundReport(
            summary=build_auto_sell_summary(
                round_no=round_no,
                session_state=candidate_round.session_state,
                candidates=candidate_round.candidates,
                block_details=block_details,
                execution_details=execution_details,
                duration_ms=elapsed_ms(started_at, timer()),
            ),
            block_details=tuple(block_details),
            execution_details=tuple(execution_details),
        )
```

```python
def run_auto_sell(
    config_path: Path,
    once: bool,
    max_rounds: int | None,
    reconcile_timeout_seconds: int,
) -> int:
    config = load_config(config_path)
    connect_gateways_for_trading(config)

    round_no = 1
    while True:
        log_round_started(entry="auto_sell", round_no=round_no)
        try:
            report = auto_sell_service.run_round(
                config=config,
                round_no=round_no,
                reconcile_timeout_seconds=reconcile_timeout_seconds,
            )
        except Exception as exc:
            emit_auto_sell_round_error(round_no=round_no, exc=exc)
            return 1

        emit_auto_sell_round_summary(report.summary)
        emit_sell_block_details(report.block_details)
        emit_sell_execution_details(report.execution_details)

        if once or reached_max_rounds(round_no, max_rounds):
            return 0

        sleep(config.poll_interval_seconds)
        round_no += 1
```

自动卖出入口的关键语义：

- 与决策观测入口复用同一条共享评估管线
- 在候选结果之上继续做卖量规划、发单、轮询和收口
- 保持真实交易语义
- 单轮异常立即退出，避免在不确定状态下继续发单

#### 4.4.4 调试脚本 `tools/debug`

```python
def check_connectivity(config_path: Path) -> int:
    config = load_config(config_path)
    connect_trade_gateway(config)
    connect_market_gateway(config)
    summary = collect_account_and_quote_summary(config)
    print_json(summary)
    return 0


def manual_trade(...trade_args...) -> int:
    config = load_config(config_path)
    connect_trade_gateway(config)
    report = submit_and_verify_manual_order(config, ...trade_args...)
    print_json(report)
    return 0 if report.verification_passed else 1
```

调试脚本与正式产品入口的关系：

- 可复用 gateway、模型和部分底层能力
- 不复用正式自动卖出入口
- 不进入正式交付口径

## 5. 模块职责与共享层

### 5.1 双状态模型保留

本次不合并“决策态”和“执行态”，仍保留双状态模型。

原因：

- 决策态回答“该不该卖、为什么、当前是否允许提单”
- 执行态回答“是否已发单、订单走到哪一步、是否终态收口”

这两类事实天然不同，若强行合并，会形成状态拼盘并恶化可维护性。

### 5.2 共享能力层

正式自动卖出入口与正式决策观测入口应共享“决策能力层”，但不直接复用彼此的服务入口。

建议的共享能力层如下：

- `SellDecisionEngine`
  - 纯规则判断
  - 回答当前持仓是否满足卖出条件
- `PositionDecisionStateStore`
  - 维护按 `symbol` 的决策状态
  - 记录触发、阻断、可卖数量、可提交状态等事实
- `SellCandidatePipeline`
  - 负责拉取持仓、拉取行情、同步决策状态、调用决策引擎并产出候选评估结果

在此基础上：

- `DecisionObserverService` 复用 `SellCandidatePipeline`，只做观测输出
- `AutoSellService` 复用 `SellCandidatePipeline` 的评估结果，再继续完成卖量规划、发单、查单、成交回报和审计收口

### 5.3 执行能力层

执行能力层独立于决策能力层，至少包含：

- `SellQuantityPolicy`
  - 负责卖量规划和归一化
- `OrderExecutionStateStore`
  - 负责按标的维护执行状态机
- `AutoSellService`
  - 作为真实交易编排层

### 5.4 未来市场扩展能力的预留方向

未来如果确实启动市场扩展能力，可以独立演进出以下模块：

- `MarketContextPipeline`
- `MarketBreadthCalculator`
- `LeaderLaggingAnalyzer`
- `NotificationPipeline`

这些能力不应依附于 `AutoSellService`，也不应被 `DecisionObserverService` 隐式承载。本次设计只保留这一约束，不把这些模块纳入当前实现范围。

## 6. 命名重构方案

### 6.1 正式运行链路命名

建议重命名如下：

| 旧命名 | 新命名 |
| --- | --- |
| `m2_decision_engine.py` | `sell_decision_engine.py` |
| `m2_state_manager.py` | `position_decision_state.py` |
| `m2_dry_run.py` | `decision_observer.py` |
| `m3_quantity_rules.py` | `sell_quantity_policy.py` |
| `m3_state_manager.py` | `order_execution_state.py` |
| `m3_execution_service.py` | `auto_sell_service.py` |
| `bootstrap.py` | `app_runner.py` 或 `runtime_bootstrap.py` |

类名建议同步重命名：

| 旧类名 | 新类名 |
| --- | --- |
| `M2DecisionEngine` | `SellDecisionEngine` |
| `M2StateManager` | `PositionDecisionStateStore` |
| `M2DryRunService` | `DecisionObserverService` |
| `M3PositionStateManager` | `OrderExecutionStateStore` |
| `M3ExecutionService` | `AutoSellService` |

### 6.2 调试工具命名

`M0` 与 `M1` 不再属于正式产品模块，改为调试工具：

| 旧命名 | 新位置 |
| --- | --- |
| `m0_connectivity.py` | `tools/debug/check_connectivity.py` |
| `m1_manual_trade.py` | `tools/debug/manual_trade.py` |

原则是：

- 保留能力，不保留阶段身份
- 退出正式 `main.py` 入口
- 作为辅助排障能力存在

### 6.3 JSON / 日志事件命名

结构化输出统一去阶段化：

| 旧 `kind` | 新 `kind` |
| --- | --- |
| `m2_round_summary` | `decision_round_summary` |
| `m2_change_detail` | `decision_change_detail` |
| `m2_round_error` | `decision_round_error` |
| `m3_round_summary` | `auto_sell_round_summary` |
| `m3_block_detail` | `sell_block_detail` |
| `m3_execution_detail` | `sell_execution_detail` |
| `m3_round_error` | `auto_sell_round_error` |

运行日志中不再记录 `mode=m2/m3`，改为真实入口标识，例如：

- `entry=decision_observer`
- `entry=auto_sell`

### 6.4 配置与示例命名

示例配置与默认 `strategy_name` 一并去阶段化，例如：

- `gmtrade-live-m0` -> `gmtrade-live-auto-sell`

配置字段不得再引导用户通过“阶段号”理解系统。

## 7. CLI 设计

### 7.1 正式产品入口

正式产品入口只保留自动卖出运行语义。

建议保留的参数包括：

- `--config`
- `--once`
- `--max-rounds`
- `--reconcile-timeout-seconds`

正式入口不再保留：

- `--mode m0`
- `--mode m1`
- `--mode m2`
- `--mode m3`

### 7.2 决策观测入口

决策观测作为独立正式入口存在，但不挂载在阶段式 `mode` 下。

其职责仅限：

- 轮询观测
- 输出摘要与变化
- 帮助人工或系统理解当前卖出候选状态

### 7.3 调试脚本入口

调试脚本入口位于 `tools/debug/` 下，职责包括：

- 连通性检查
- 手工卖单 / 手工买单验证
- 查单链路排障

调试脚本不进入正式产品入口，也不进入对外交付主说明。

## 8. 测试、日志、文档与配置收口

### 8.1 测试命名

测试文件按能力而非阶段命名：

- `test_m2_*` -> `test_decision_*` 或 `test_sell_decision_*`
- `test_m3_*` -> `test_auto_sell_*` 或 `test_order_execution_*`
- `test_m4_local_smoke.py` -> `test_release_smoke.py` 或 `test_auto_sell_smoke.py`

调试工具测试迁移到：

- `tests/debug/`
- 或 `tests/tools/`

### 8.2 日志与审计

日志与审计要求如下：

- 自动卖出入口保留真实执行审计
- 决策观测入口保留结构化变化输出
- 轮次日志和订单审计日志继续存在
- 字段语义去阶段化，但不弱化证据能力

错误边界保持原有语义：

- 决策观测：单轮失败可记录并继续
- 自动卖出：单轮异常立即退出

### 8.3 文档

文档入口统一改为产品语言：

- 主说明文档描述自动卖出闭环系统
- 调试文档描述 `tools/debug`
- 验收文档描述 smoke / acceptance / audit

历史 `M0~M4` 设计文档可以保留，但必须降级为研发历史资料，不再充当主阅读入口。

### 8.4 配置

配置与示例文件必须统一去阶段化，避免继续传播旧语义。

## 9. 迁移策略

### 9.1 分阶段迁移顺序

推荐按以下顺序实施：

1. 建立新语义骨架
2. 迁移内部模块名、类名、日志事件名
3. 切换正式 CLI 与主文档
4. 迁出 `M0/M1` 到 `tools/debug`
5. 清理旧阶段暴露

### 9.2 兼容策略

本次不保留长期双命名。

允许在重构过程中的短时间提交里存在新旧名并存，但主干最终形态必须彻底去阶段化，否则会长期形成双语义系统。

## 10. 风险与约束

### 10.1 不改变交易语义

本次重构只改边界、命名与职责表达，不改变：

- 策略规则
- 卖量归一化规则
- 自动卖出异常即停边界
- 决策观测的观察型语义

### 10.2 不打断证据链

重构后仍必须保留可复核证据：

- CLI JSON 输出
- `runtime.log`
- `order_audit.log`
- smoke 测试与验收记录

### 10.3 不让观测入口承担交易职责

观测入口必须保持只读语义，不能通过“复用方便”逐步变成半个交易入口。

### 10.4 不让未来市场扩展污染当前交易主链

未来即便新增三年日 K、市场情绪、领涨领跌、飞书通知，也必须沿独立扩展边界演进；当前交易主链只能通过显式输入边界读取上下文结果。

## 11. 完成标准

本设计落地完成后，仓库主干应满足：

- 正式入口不再暴露 `M0~M4`
- 正式自动卖出入口与正式决策观测入口命名真实
- `M0/M1` 已迁移为 `tools/debug` 调试脚本
- 测试、日志、文档、配置全部去阶段化
- 自动卖出主链与未来市场扩展边界清晰
- 主干不保留长期双命名

## 12. 推荐提交拆分

建议按以下提交粒度实施：

1. `refactor(core): rename staged decision and execution modules`
2. `refactor(cli): replace staged modes with product entrypoints`
3. `refactor(debug): move connectivity and manual trade into tools/debug`
4. `refactor(observability): rename structured logs and smoke assets`
5. `docs(product): rewrite docs and config examples for auto-sell product language`
