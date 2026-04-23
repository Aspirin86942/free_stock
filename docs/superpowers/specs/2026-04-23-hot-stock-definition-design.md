# 热门股样本定义补齐设计

日期：2026-04-23

## 1. 背景

当前盘后市场分析链路已经在赚钱效应与容错指标中使用了“热门股”样本，但现状存在两个问题：

1. 热门股定义没有收敛成统一边界，而是分散在 analyzer 内部条件判断中。
2. 设计文档要求“排除次新股（上市日至前一交易日之间的实际交易日数 < 250）”，但当前实现没有落地这一条。

用户当前确认的目标很明确：

- 只补齐 analyzer 内部的热门股样本定义。
- 不新增热门股独立清单输出能力。
- 不扩展交易链路，不把热门股引入自动交易主链。
- 次新股过滤必须按“上市日至前一交易日之间的实际交易日数 < 250 就排除”执行，不能用自然日近似替代。

## 2. 目标与非目标

### 2.1 目标

本次设计完成后，系统应满足以下目标：

1. 热门股定义在盘后分析链路中有唯一实现口径。
2. `MarketProfitEffectAnalyzer` 与 `MarketToleranceAnalyzer` 复用同一套热门股解析逻辑。
3. 热门股样本满足以下全部条件：
   - 基于前一交易日 `T-1` 判定；
   - 非 `ST`；
   - 非停牌；
   - 有成交；
   - 昨日收盘价 `> 10`；
   - 昨日换手率 `> 10%`；
   - 上市日至 `T-1` 之间的实际交易日数 `>= 250`。
4. 缺少上市日期或缺少交易日历支撑时，热门股样本按保守策略排除，不做猜测。
5. 为热门股边界补齐单元测试，至少覆盖“不足 250 个交易日排除”和“恰好 250 个交易日保留”。

### 2.2 非目标

本次设计不包含以下事项：

1. 不新增热门股名单导出、日志明细或飞书明细展示。
2. 不修改飞书消息结构。
3. 不修改自动交易链路，不引入热门股驱动的买卖决策。
4. 不引入第三方数据源。
5. 不顺带重构全部 analyzer，只做与热门股口径直接相关的最小必要改动。

## 3. 方案对比与选择

### 方案 A：分别在两个 analyzer 内各自补过滤条件

- 做法：在 `MarketProfitEffectAnalyzer` 与 `MarketToleranceAnalyzer` 内分别补次新股过滤逻辑。
- 优点：改动表面上最直接。
- 缺点：热门股定义会复制两份；后续只要口径再变一次，就容易出现一边更新、一边遗漏。

### 方案 B：新增共享热门股解析器（选中）

- 做法：把热门股定义收敛到一个共享组件，例如 `HotStockResolver`，由 analyzer 调用。
- 优点：
  - 口径唯一；
  - 测试边界集中；
  - 后续若再调整热门股定义，只需改一个地方。
- 成本：
  - 需要给 repository 补充上市日期查询能力；
  - 需要补一个“按日期范围获取交易日”的基础查询能力。

### 方案 C：把热门股筛选下沉到 repository SQL

- 做法：repository 直接返回热门股样本。
- 优点：表面上查询集中。
- 缺点：repository 会直接承载业务口径，破坏“仓储层只负责数据访问、服务层负责业务规则”的边界。

### 结论

选择方案 B：新增共享热门股解析器。

原因：

1. 热门股是共享业务规则，不应散落在多个 analyzer 内部。
2. 当前项目已有明确分层约束，repository 只适合提供数据，不适合直接承载完整业务样本定义。
3. 本次需求规模不大，但如果继续复制逻辑，会把后续维护成本放大。

## 4. 设计结论

### 4.1 新增共享边界

新增一个共享服务，例如：

- `src/gmtrade_live/services/hot_stock_resolver.py`

职责只做一件事：

- 根据分析日 `trade_date` 解析出该分析日应使用的热门股样本集合。

该组件不负责计算收益、不负责计算回撤、不负责发送消息，只负责“哪些 symbol 属于热门股”。

### 4.2 热门股判定口径

对分析日 `T`：

1. 先取最近两个交易日，找到前一交易日 `T-1`。
2. 用 `T-1` 的日线作为热门股筛选基准。
3. 仅当以下条件全部满足时，某股票才进入热门股样本：
   - `has_trade is True`
   - `suspended is False`
   - `is_st is False`
   - `close > Decimal("10")`
   - `turnover_rate > 10%`
   - `listed_date` 存在
   - `listed_date` 至 `T-1` 之间的实际交易日数 `>= 250`

### 4.3 次新股过滤口径

次新股过滤必须遵守以下语义：

1. 计数区间为 `listed_date` 到前一交易日 `T-1`。
2. 使用“市场实际交易日数”，不是自然日差值。
3. 若 `listed_date` 本身不是交易日，则只统计区间内真实存在的交易日。
4. 若交易日数 `< 250`，则视为次新股，必须排除。
5. 若交易日数 `>= 250`，则允许进入热门股样本。

这里采用保守口径，原因是：

- 设计要求明确指定“实际交易日数”；
- 自然日近似会受到节假日、长假、停市日影响，结果不可审计；
- 盘后分析指标是事后统计，宁可少算，不可乱算。

### 4.4 repository 需要补的能力

为支持上述规则，repository 需要补两类基础数据访问能力：

1. `symbol -> listed_date` 映射查询
   - 输入：`symbols: list[str]`
   - 输出：`dict[str, date]`
   - 数据来源：`market_security_master.listed_date`

2. 日期区间交易日查询
   - 输入：`start_date: date`, `end_date: date`
   - 输出：`list[date]`
   - 数据来源：`market_daily_bar.trade_date` 的去重结果

第二个能力只负责返回日期列表，不负责热门股语义判断。

### 4.5 analyzer 接入方式

接入后，两个 analyzer 应按以下方式收敛：

1. `MarketProfitEffectAnalyzer`
   - 不再自己拼热门股条件；
   - 改为通过 `HotStockResolver` 获取 `hot_symbols`；
   - 继续只负责“热门股 4 日平均收益”的收益计算。

2. `MarketToleranceAnalyzer`
   - 不再自己拼热门股条件；
   - 改为通过 `HotStockResolver` 获取 `hot_symbols`；
   - 继续只负责“热门股收盘高于均价占比”和“热门股日内最大回撤中位数”的计算。

### 4.6 缺失数据语义

若发生以下任一情况，热门股解析器必须走保守降级：

1. 取不到 `T-1`；
2. `T-1` 没有任何日线数据；
3. 某 symbol 缺少 `listed_date`；
4. 交易日区间为空或不足以支撑判断；
5. `turnover_rate` 为空。

降级规则：

- 对单个 symbol 缺失上市日期或换手率时，只排除该 symbol；
- 若整体无法确定 `T-1` 或无法获得交易日列表，则返回空集；
- 不得因为数据不完整而把样本误放宽。

### 4.7 可观测性要求

本次不新增报表字段，但仍应保留最小必要日志语义：

1. 热门股解析开始时记录分析日。
2. 热门股解析结束时记录热门股数量。
3. 若因缺少前一交易日或交易日历导致返回空集，应记录原因。

日志目标是帮助审计“为什么今天热门股样本为空”，而不是输出详细名单。

## 5. 数据流

### 5.1 主流程

1. analyzer 收到分析日 `T`
2. analyzer 调用 `HotStockResolver.resolve(T)`
3. `HotStockResolver`：
   - 读取最近两个交易日；
   - 确认 `T-1`；
   - 读取 `T-1` 全量日线；
   - 读取对应证券的上市日期；
   - 读取 `listed_date -> T-1` 区间交易日；
   - 应用热门股规则；
   - 返回 `hot_symbols`
4. analyzer 使用 `hot_symbols` 继续做指标计算

### 5.2 边界原则

数据访问边界：

- repository 提供“查什么数据”的能力；
- resolver 负责“这些数据如何组合成热门股语义”；
- analyzer 负责“热门股样本拿到后如何计算指标”。

这样做的原因是：

- repository 保持纯数据访问；
- resolver 成为热门股定义唯一实现；
- analyzer 不需要知道上市日期和交易日计数细节，职责更单一。

## 6. 测试设计

### 6.1 必测场景

至少覆盖以下场景：

1. 上市不足 `250` 个实际交易日
   - 即使价格、换手率、成交状态全部满足，也必须排除。

2. 上市恰好 `250` 个实际交易日
   - 必须保留。

3. 缺少 `listed_date`
   - 必须排除。

4. `turnover_rate` 为空
   - 必须排除。

5. `MarketProfitEffectAnalyzer` 与 `MarketToleranceAnalyzer` 都通过共享 resolver 生效
   - 不能只修一个 analyzer。

### 6.2 测试策略

优先使用单元测试完成验证：

1. 为 resolver 单独补测试，验证热门股判定边界。
2. 为 analyzer 补回归测试，验证接入共享 resolver 后指标结果仍符合预期。
3. 为 repository 补基础查询测试，验证上市日期映射与交易日区间查询语义。

## 7. 风险与边界条件

1. `market_daily_bar` 的交易日集合来自已同步事实表。
   - 若事实表自身缺历史缺口，交易日数也会被低估。
   - 这是现有数据源边界，不在本次设计内解决。

2. `turnover_rate` 当前可能为空。
   - 该情况下热门股样本会保守收缩。
   - 这是符合现有口径说明的。

3. `is_st` 当前仍有 best-effort 限制。
   - 本次不改变 ST 数据来源。
   - 热门股定义继续按现有 `DailyBar.is_st` 结果执行。

4. 单只股票逐只查交易日列表会有重复计算风险。
   - 实现时应避免对每个 symbol 重复查询同一段交易日。
   - 更合理的方式是先取一次区间交易日，再基于 `listed_date` 做计数判断。

## 8. 目标 / 输入 / 输出 / 伪代码草案

### 8.1 目标

把热门股定义收敛成一个共享解析逻辑，并严格落地“实际交易日数 >= 250”这一条。

### 8.2 输入

- `trade_date`: 当前分析日
- `repository`: 提供日线、上市日期、交易日查询能力的数据访问对象
- 上下文约束：只使用现有 `gm + MySQL` 事实源

### 8.3 输出

- 成功返回：`set[str]`，表示热门股 symbol 集合
- 降级返回：空集合 `set()`
- 不额外抛业务异常；缺失数据时优先保守排除并记日志

### 8.4 伪代码草案

```python
# [伪代码草案]
# 目标：统一解析指定分析日的热门股样本，并把“实际交易日数 >= 250”纳入硬约束
# 输入：
# - trade_date: 当前分析日 T
# - repository: 提供前一交易日、日线、上市日期、交易日列表查询能力
# 输出：
# - hot_symbols: 满足热门股规则的股票集合
# - empty_set: 在关键数据不足时返回空集合，而不是猜测结果

def resolve_hot_symbols(trade_date, repository):
    # 1. 先确认分析日是否存在前一交易日；没有 T-1 就无法定义“昨日热门股”
    recent_dates = repository.get_recent_trade_dates(trade_date, 2)
    if len(recent_dates) < 2:
        log_info("hot_stock_resolver.no_previous_trade_date", trade_date=trade_date)
        return set()

    previous_trade_date = recent_dates[-2]

    # 2. 读取前一交易日全量日线；热门股定义必须以 T-1 为判定基准
    previous_bars = repository.get_daily_bars_by_date(previous_trade_date)
    if not previous_bars:
        log_info(
            "hot_stock_resolver.no_previous_bars",
            trade_date=trade_date,
            previous_trade_date=previous_trade_date,
        )
        return set()

    symbols = [bar.symbol for bar in previous_bars]
    listed_date_map = repository.get_security_listed_date_map(symbols)

    # 3. 区间交易日只取一次，避免每只股票重复查询
    earliest_listed_date = min(listed_date_map.values(), default=None)
    if earliest_listed_date is None:
        log_info(
            "hot_stock_resolver.no_listed_dates",
            trade_date=trade_date,
            previous_trade_date=previous_trade_date,
        )
        return set()

    trade_dates = repository.get_trade_dates_between(
        earliest_listed_date,
        previous_trade_date,
    )
    trade_date_index = {trade_date: index for index, trade_date in enumerate(trade_dates)}

    hot_symbols = set()

    for bar in previous_bars:
        # 4. 先过滤显式不满足条件的股票，避免做多余计算
        if not bar.has_trade or bar.suspended or bar.is_st:
            continue

        if bar.close <= Decimal("10"):
            continue

        if not is_turnover_over_10(bar.turnover_rate):
            continue

        listed_date = listed_date_map.get(bar.symbol)
        # 为什么这样做：
        # 缺少上市日期时无法判断是不是次新股，继续放行会把样本做大，所以必须保守排除
        if listed_date is None:
            continue

        # 5. 用“实际交易日数”判断是否次新，而不是自然日差值
        listed_trade_index = trade_date_index.get(first_trade_date_on_or_after(listed_date, trade_dates))
        previous_trade_index = trade_date_index.get(previous_trade_date)
        if listed_trade_index is None or previous_trade_index is None:
            continue

        trading_days_since_listing = previous_trade_index - listed_trade_index + 1
        if trading_days_since_listing < 250:
            continue

        hot_symbols.add(bar.symbol)

    log_info(
        "hot_stock_resolver.resolved",
        trade_date=trade_date,
        previous_trade_date=previous_trade_date,
        hot_stock_count=len(hot_symbols),
    )
    return hot_symbols
```

### 8.5 风险点 / 边界条件

1. 若事实表交易日不完整，上市交易日数会被低估。
2. 若上市日期早于事实表最早交易日，解析器只能在当前事实表覆盖范围内判断。
3. 若未来热门股定义继续增加条件，应继续只改 resolver，不应再次扩散到 analyzer。

## 9. 实施结论

本次热门股补齐不应作为“顺手补一条 if”的局部修补，而应作为共享规则收敛处理。

最终实施方向为：

1. repository 补足上市日期与区间交易日查询能力；
2. 新增共享 `HotStockResolver`；
3. 两个 analyzer 改为依赖 resolver；
4. 用单测锁定“<250 排除、=250 保留”的关键边界。
