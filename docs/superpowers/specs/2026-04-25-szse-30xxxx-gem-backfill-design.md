# 创业板 `SZSE.30xxxx` 识别修正与 `301` 历史补数设计

日期：2026-04-25

## 1. 背景

当前市场分析链路的股票池来自 `GMHistoryMarketGateway.get_security_master()`。该方法现在只把 `SZSE.300xxx` 识别为创业板，把 `SHSE.688xxx` 识别为科创板，把 `SHSE.6xxxxxx` 与 `SZSE.0xxxxxx` 识别为主板。

这带来一个已被数据库事实验证的问题：

1. `SZSE.301xxx` 当前不会被识别为创业板，而是直接落入“其他”分支被跳过。
2. 因为证券主数据没有纳入 `301`，后续 `market_security_master` 与 `market_daily_bar` 中都没有 `301` 数据。

已核实的数据库现状如下：

1. `market_security_master` 中 `SZSE.301%` 数量为 `0`
2. `market_daily_bar` 中 `SZSE.301%` 数量为 `0`
3. `market_security_master` 中 `SZSE.30%` 数量为 `943`
4. 这 `943` 条全部是 `SZSE.300%`

因此，本次需求不能只停留在“修一条板块识别规则”，还必须解决“过去已经漏掉的 `301` 如何补回”的问题。

## 2. 目标与非目标

### 2.1 目标

本次设计完成后，系统应满足以下目标：

1. 所有 `SZSE.30xxxx` 股票都被识别为创业板 `gem`
2. `SZSE.301xxx` 进入 `market_security_master`
3. 已经漏掉的 `SZSE.301xxx` 历史日线数据可以被补入 `market_daily_bar`
4. 修复后再次生成盘后分析报告时，`301` 股票能够参与股票池、补数与后续市场统计
5. 用单元测试锁定新的板块识别规则与补数行为，避免未来回退

### 2.2 非目标

本次设计不包含以下事项：

1. 不修改市场宽度、赚钱效应、容错、情绪等指标公式
2. 不修改飞书消息结构
3. 不引入新的股票池配置值
4. 不扩展到北交所、指数、ETF 或其他证券类型
5. 不顺带重构整套同步架构，只做与 `SZSE.30xxxx` 识别和 `301` 补数直接相关的最小必要改动

## 3. 问题根因

### 3.1 创业板识别根因

当前实现按前缀判断板块：

1. `SHSE.688` -> `star`
2. `SZSE.300` -> `gem`
3. `SHSE.6` 或 `SZSE.0` -> `main`
4. 其他 -> 跳过

这意味着：

1. `SZSE.300xxx` 会进入创业板
2. `SZSE.301xxx` 不满足任何已知分支
3. `SZSE.301xxx` 会被直接过滤掉

### 3.2 历史漏库无法自动自愈的根因

即使修正了证券识别规则，现有同步逻辑也不能自动把过去几年漏掉的 `301` 补回来，原因有两个：

1. 当没有新交易日时，`MarketDataSyncService.sync()` 会在刷新股票池前直接返回
2. 即使有新交易日，增量同步也只会从当前 checkpoint 的下一个交易日开始拉取，无法回补更早的历史日期

因此，单独修改创业板识别规则只能影响“未来”，不能修复已经存在的历史缺口。

## 4. 方案对比与选择

### 方案 A：只改证券识别规则

- 做法：把 `SZSE.301xxx` 纳入创业板识别，其他逻辑不动
- 优点：改动最小
- 缺点：
  - 历史漏库仍然存在
  - 数据库事实不会自动修复
  - 用户当前已确认“之前确实的 301 都没有进行落库”，该方案无法满足目标

### 方案 B：改证券识别规则 + 新增 `301` 缺口补数路径（选中）

- 做法：
  - 把所有 `SZSE.30xxxx` 统一识别为创业板
  - 在同步链路中补一条专门针对“新纳入证券但历史缺失”的回补路径
- 优点：
  - 同时解决未来与历史问题
  - 行为范围仍然聚焦在 `SZSE.30xxxx` / `301` 上
  - 不需要重做全量三年数据同步
- 成本：
  - 同步服务需要新增“识别新纳入 symbol 并回补历史”的逻辑
  - 需要补对应单元测试

### 方案 C：直接人工删 checkpoint 或清空表后重新全量同步

- 做法：通过手工运维方式强制系统重新跑全量历史
- 优点：代码改动少
- 缺点：
  - 运维成本高
  - 风险大
  - 依赖人工步骤，不可重复审计
  - 不适合作为正式修复方案

### 结论

选择方案 B：

1. 规则修正必须落地，否则 `301` 以后还会继续漏
2. 历史补数必须代码化，否则数据库缺口永远存在
3. 该方案既满足当前问题，也保持在最小必要范围内

## 5. 设计结论

### 5.1 证券主数据识别规则

`GMHistoryMarketGateway.get_security_master()` 的板块识别改为：

1. `SHSE.688xxxx` -> `star`
2. `SZSE.30xxxx` -> `gem`
3. `SHSE.6xxxxxx` 或 `SZSE.0xxxxxx` -> `main`
4. 其他 -> 跳过

这里显式采用 `SZSE.30xxxx` 而不是继续写死 `300` / `301` 两个前缀，原因是：

1. 用户已经明确确认要收敛成更泛的创业板规则
2. 当前需求的业务语义是“深市 30 段股票归创业板”，不是“只补一个号段再继续打补丁”

### 5.2 同步主流程修正

`MarketDataSyncService.sync()` 需要补两个行为修正：

1. **股票池刷新前置**
   - 无论是否存在新交易日，都应先刷新一次股票池
   - 这样即使当天没有新交易日，`market_security_master` 也能先纳入新的 `SZSE.30xxxx` 证券

2. **新纳入证券历史回补**
   - 在刷新股票池后，对比“当前股票池 symbol 集合”和“数据库已有 symbol 集合”
   - 对本轮新出现的 symbol，单独执行历史回补
   - 历史回补起始日应与首次同步口径一致，即近 `history_years` 年起点
   - 历史回补结束日应取当前最新已完成交易日

### 5.3 为什么不直接复用普通增量同步

普通增量同步的输入是：

1. 起始日期：`checkpoint` 的下一个交易日
2. 证券范围：当前股票池

问题在于：

1. 新纳入证券虽然出现在股票池里
2. 但其历史数据在 checkpoint 之前已经全部错过
3. 普通增量同步只会拉当前窗口，不会主动补旧日期

因此，必须把“新纳入 symbol 的历史回补”作为显式分支处理，不能寄希望于现有增量逻辑自动覆盖。

### 5.4 新纳入证券识别口径

“新纳入证券”定义为：

1. 已存在于 `gateway.get_security_master()` 返回的股票池中
2. 但不存在于 `market_security_master` 已落库 symbol 集合中

该定义的好处是：

1. 直接反映“本轮修正规则后新增进来的 symbol”
2. 不依赖是否已有部分日线数据
3. 能优先解决当前 `301` 完全未落库的问题

### 5.5 历史回补范围

对“新纳入证券”的历史回补范围采用以下规则：

1. 起始日期：`gateway.get_trade_date_n_years_ago(history_years)`
2. 结束日期：`gateway.get_latest_trade_date()`
3. 证券范围：仅本轮新纳入证券

这意味着：

1. 不会对全市场重复拉一遍三年数据
2. 只会对缺失的新 symbol 做定向补数
3. 与现有三年回补口径保持一致，便于审计

### 5.6 与现有增量逻辑的关系

主流程建议收敛为：

1. 读取 checkpoint 与事实表最新交易日
2. 计算本轮普通增量的日期窗口
3. 获取最新股票池
4. 先写入 `market_security_master`
5. 识别新纳入证券
6. 若存在新纳入证券，则对其执行历史回补
7. 再对全股票池执行普通增量同步
8. 最后更新 checkpoint

这样做的原因是：

1. 新纳入证券的历史补数与全市场普通增量是两个不同问题
2. 两者分开处理，语义清楚、测试边界明确
3. 即使当天无新交易日，也可以完成“股票池刷新 + 新纳入证券历史补数”

### 5.7 无新交易日场景的语义

当 `start_date > end_date` 时，不能再像现在一样直接返回；应改为：

1. 仍然刷新股票池
2. 仍然识别新纳入证券
3. 若存在新纳入证券，则允许执行其历史回补
4. 仅当“既无普通增量，又无新纳入证券需要历史回补”时，才进入近期换手率修复并返回

这是本次设计的关键修正点之一，因为当前 `301` 漏库正是在这种场景下无法自愈。

## 6. 数据流

### 6.1 主流程

1. `sync()` 读取 checkpoint 与事实表最新交易日
2. 计算普通增量窗口
3. 获取当前股票池 `securities`
4. 查询数据库中已存在的 symbol 集合
5. 计算 `new_symbols = current_symbols - existing_symbols`
6. 写入或更新 `market_security_master`
7. 若 `new_symbols` 非空，则对 `new_symbols` 执行近 `history_years` 年历史回补
8. 若普通增量窗口有效，则对全股票池执行普通增量同步
9. 更新 checkpoint
10. 若无普通增量且无新 symbol 历史回补，则执行近期换手率修复

### 6.2 边界原则

1. 网关负责“从掘金拿到什么证券、什么历史日线”
2. 同步服务负责“如何决定哪些 symbol 需要历史补数”
3. 仓储负责“主数据与日线如何落库”

不把“新纳入 symbol 历史回补”塞进仓储或网关，是为了保持职责边界清晰。

## 7. 测试设计

### 7.1 必测场景

至少覆盖以下场景：

1. `get_security_master()` 能把 `SZSE.300001` 识别为 `gem`
2. `get_security_master()` 能把 `SZSE.301001` 识别为 `gem`
3. `get_security_master()` 继续排除不在目标范围内的 symbol
4. 当没有新交易日，但股票池里出现新 symbol 时，`sync()` 仍会刷新主数据并触发该 symbol 的历史回补
5. 当存在普通增量且存在新 symbol 时，`sync()` 会同时执行“新 symbol 历史回补 + 全市场普通增量”
6. 若没有新交易日且没有新 symbol，`sync()` 仍保持现有“近期换手率修复”语义

### 7.2 测试策略

优先用单元测试锁定行为：

1. 在 `tests/unit/test_gm_history_market_gateway.py` 中补创业板识别用例
2. 在 `tests/unit/test_market_data_sync_service.py` 中补“无新交易日也能补新 symbol 历史”的用例
3. 在 `tests/unit/test_market_data_sync_service.py` 中补“新 symbol 历史补数 + 普通增量并存”的用例

## 8. 风险与边界条件

1. 若 `market_security_master` 已有 symbol，但其历史日线只缺一部分，本次“新 symbol = 当前股票池减已落库 symbol”无法识别这种部分缺口
2. 当前用户确认的问题是 `301` 完全未落库，因此本次设计优先解决“完全缺失的新纳入证券”场景
3. 若后续要修复“已存在主数据但历史日线部分缺失”的问题，应另起设计，不应在本次需求里混入
4. 新增历史回补会增加一次额外的网关请求，但范围只限于新纳入证券，成本可控
5. 若掘金接口对部分新 symbol 返回空历史，应保留现有 best-effort 语义，不可静默伪造数据

## 9. 目标 / 输入 / 输出 / 伪代码草案

### 9.1 目标

让系统既能正确识别所有 `SZSE.30xxxx` 创业板证券，又能把历史上漏掉的 `301` 主数据和日线数据补齐。

### 9.2 输入

- `market_analysis_config.history_years`
- `checkpoint`：`market_daily_sync`
- `latest_trade_date_in_daily_bar`
- `gateway.get_security_master(universe)`
- `repository.get_all_symbols()`
- `gateway.fetch_daily_bars(symbols, start_date, end_date)`

### 9.3 输出

- 成功返回：`SyncResult`
- 成功副作用：
  - `market_security_master` 纳入新的 `SZSE.30xxxx`
  - `market_daily_bar` 补入新纳入 symbol 的历史日线
  - 若存在新交易日，则继续完成普通增量同步
- 失败返回：沿用现有结构化异常，不允许静默失败

### 9.4 伪代码草案

```python
# [伪代码草案]
# 目标：在保持现有增量同步能力的同时，补齐新纳入证券的历史缺口
# 输入：
# - config: 包含 history_years 和 universe
# - gateway: 提供股票池、交易日和历史日线拉取能力
# - repository: 提供 checkpoint、已落库 symbol、主数据落库和日线落库能力
# 输出：
# - sync_result: 同步结果，包含最新交易日和影响行数

def sync_market_data(config, gateway, repository):
    # 1. 先计算普通增量窗口，但不在这一步提前返回
    checkpoint_date = repository.get_last_success_trade_date("market_daily_sync")
    latest_bar_date = repository.get_latest_trade_date_in_daily_bar()
    effective_checkpoint_date = reconcile_checkpoint(checkpoint_date, latest_bar_date, repository)
    latest_trade_date = gateway.get_latest_trade_date()
    incremental_start_date = resolve_incremental_start_date(
        effective_checkpoint_date,
        config.history_years,
        gateway,
    )

    # 2. 先刷新股票池；为什么这样做：
    # 当前问题的根因之一就是“无新交易日时直接返回”，导致 301 连主数据都进不来
    securities = gateway.get_security_master(config.universe)
    current_symbols = [security.symbol for security in securities]
    existing_symbols = set(repository.get_all_symbols())
    new_symbols = [symbol for symbol in current_symbols if symbol not in existing_symbols]

    repository.upsert_security_master(securities)

    total_affected_rows = 0

    # 3. 对新纳入 symbol 做历史回补；为什么单独做：
    # 普通增量只看 checkpoint 之后，无法补回过去已经错过的几千个历史交易日
    if new_symbols:
        history_start_date = gateway.get_trade_date_n_years_ago(config.history_years)
        history_bars = gateway.fetch_daily_bars(
            new_symbols,
            history_start_date,
            latest_trade_date,
        )
        if history_bars:
            total_affected_rows += repository.upsert_daily_bars(history_bars)

    # 4. 再做普通增量同步；这样未来新交易日仍沿用现有机制
    if incremental_start_date <= latest_trade_date:
        for batch_symbols in chunk(current_symbols, 50):
            incremental_bars = gateway.fetch_daily_bars(
                batch_symbols,
                incremental_start_date,
                latest_trade_date,
            )
            if incremental_bars:
                total_affected_rows += repository.upsert_daily_bars(incremental_bars)
        update_checkpoint_if_needed(repository, effective_checkpoint_date, latest_trade_date)
    else:
        # 5. 只有在“无普通增量且无新 symbol 历史回补”时，才退回近期换手率修复
        if not new_symbols:
            total_affected_rows += repair_recent_turnover_if_needed(
                repository,
                gateway,
                latest_bar_date or latest_trade_date,
            )

    return build_sync_result(total_affected_rows, latest_trade_date)
```

### 9.5 风险点 / 边界条件

1. 若本轮新纳入 symbol 数量很少，历史回补应按单独批次执行，不应触发全市场重扫
2. 若后续还出现其他因股票池规则变更导致的新 symbol，本方案也应能复用，不要把逻辑写死成“仅 301 特判”
3. 若未来需要修“部分历史缺口”而非“整只证券缺失”，应在另一个设计中处理更细粒度的补数策略

## 10. 实施结论

本次问题的正确修复边界是：

1. 把创业板识别从 `SZSE.300xxx` 扩成 `SZSE.30xxxx`
2. 把股票池刷新从“仅有新交易日时执行”改为“每轮同步都执行”
3. 为新纳入 symbol 新增定向历史回补路径
4. 用单元测试锁定“301 被纳入 + 历史可补回”的关键行为

只有这样，才能同时修复未来漏抓和历史漏库两个问题。
