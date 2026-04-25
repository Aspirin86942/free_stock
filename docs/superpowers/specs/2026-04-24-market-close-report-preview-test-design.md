# 飞书日报预览调试测试设计

日期：2026-04-24

## 1. 背景

当前仓库已经具备完整的盘后市场分析与飞书发送链路：

- `main.py scheduler --once` 会执行“补数 -> 分析 -> 飞书发送”
- `FeishuNotificationService` 已能把 `MarketCloseReport` 渲染为飞书纯文本消息
- 当前链路为了防止重复发送，当日已发送后会提前短路

这带来一个实际问题：

- 用户后续经常需要“只看当天飞书文本长什么样”
- 但正式 `scheduler --once` 在当日已发送后不会再生成并打印报告
- 即使强行复用发送链路，也会碰到重复发送 webhook 和污染发送 checkpoint 的风险

因此需要一个**默认无副作用**、**可手工重复运行**、**仍然使用真实配置和真实数据库**的调试入口，用来把飞书日报文本直接打印到终端。

## 2. 目标与非目标

### 2.1 目标

本次设计完成后，应满足以下目标：

- 新增一个可执行的 `pytest` 调试测试，用于打印飞书日报文本
- 该调试测试默认读取 `config/sim_account.yaml`
- 该调试测试默认连接真实 MySQL，并基于最新已落库交易日生成报告
- 调试测试打印的文本必须与飞书实际发送文案保持同源
- 调试测试默认**不发送 webhook**
- 调试测试默认**不写入或修改发送 checkpoint**
- 支持通过环境变量覆盖指定交易日，方便回看历史日报
- 更新 `AGENTS.md`，把该调试测试纳入正式调试入口说明

### 2.2 非目标

本次设计不包含以下事项：

- 不新增新的正式 CLI 子命令
- 不修改 `scheduler` 的对外语义
- 不放宽“当日日报已发送即跳过正式发送”的保护逻辑
- 不新增“强制补发飞书”的正式入口
- 不把该调试测试纳入默认全量 `pytest` 回归门禁
- 不把飞书文本另存到文件、数据库或对象存储

## 3. 方案结论

### 3.1 采用方案

采用方案 C：新增一个 `pytest` 调试测试作为飞书日报预览入口。

推荐执行命令：

```powershell
conda run -n stock_analysis pytest tests/debug/test_market_close_report_preview.py -s
```

可选地允许通过环境变量覆盖交易日：

```powershell
$env:MARKET_CLOSE_REPORT_TRADE_DATE='2026-04-24'
conda run -n stock_analysis pytest tests/debug/test_market_close_report_preview.py -s
```

### 3.2 为什么不用 CLI

不采用独立 CLI 的原因不是做不到，而是当前仓库已经把“真实环境下的手工排障入口”稳定放在两类位置：

- `tools/debug/*.py`：手工调试脚本
- `tests/debug/*.py`：带真实环境语义、但默认不进回归门禁的调试测试

本次需求本质上更接近“手工复核当前飞书文案”，而不是“新增正式运维命令”。继续沿用 `tests/debug/` 的组织方式有三个好处：

- 不扩展正式命令面，避免 CLI 入口膨胀
- 使用方式和现有调试测试一致，学习成本低
- 更容易在测试里断言基本结构，防止后续文案构建被改坏

### 3.3 为什么不能混入默认全量测试

该调试测试将依赖以下真实运行前提：

- 本地存在 `config/sim_account.yaml`
- MySQL 中已有 `market_daily_bar` 数据
- 当前环境具备访问真实数据库的能力

这类前提不满足“任何开发机、任何时间都可稳定执行”的默认门禁要求，因此它必须放在 `tests/debug/`，并由用户按需显式运行，而不能并入当前 `pytest` 默认主链。

## 4. 输入

### 4.1 显式输入

- `config/sim_account.yaml`
- 可选环境变量 `MARKET_CLOSE_REPORT_TRADE_DATE`

### 4.2 隐式输入

- `market_daily_bar` 中的已落库市场数据
- `market_security_master` 中的证券主数据
- `market_analysis.recent_trade_days` 配置值

## 5. 输出

### 5.1 成功输出

- 终端打印完整飞书纯文本日报
- 测试断言最小结构存在，例如：
  - 标题 `市场分析日报`
  - 目标交易日
  - `一眼结论`
  - `最近 10 日趋势` 或配置对应的趋势区块

### 5.2 失败输出

失败时必须明确报错，不允许静默跳过：

- 配置文件不存在
- 数据库不可连接
- `market_daily_bar` 为空，无法确定最新交易日
- 环境变量日期格式非法

### 5.3 副作用约束

必须明确保证以下副作用**不存在**：

- 不调用飞书 webhook
- 不写 `market_close_report_sent` checkpoint
- 不更新任何市场数据表

## 6. 文件与职责

### 6.1 `tests/debug/test_market_close_report_preview.py`

新增调试测试文件，职责是：

- 解析可选环境变量交易日
- 读取真实运行时配置
- 连接真实 MySQL 仓储
- 构建 `MarketCloseReport`
- 调用共享的飞书文本渲染接口
- 把最终文本 `print()` 到终端
- 对文本做最小结构断言

该文件的定位应与 `tests/debug/test_check_connectivity.py`、`tests/debug/test_manual_trade.py` 一致：  
**可手工执行、默认不进门禁、允许依赖真实环境。**

### 6.2 `src/gmtrade_live/services/feishu_notification_service.py`

当前飞书文本由私有方法 `_build_message()` 组装。为了避免调试测试直接依赖私有方法，本次应把“纯文本渲染”提取为可复用公共接口。

建议收敛为以下边界：

- 保留 `send_market_close_report(report)` 作为发送入口
- 新增公开渲染方法，例如：
  - `build_market_close_report_message(report)`
  - 或 `render_market_close_report_text(report)`

这样可以保证：

- 正式发送链路与调试测试使用同一份文案构建逻辑
- 后续如果飞书文本结构变化，只需改一处
- 不需要让测试直接调用私有 `_build_message()`

### 6.3 `AGENTS.md`

本次需要全量同步更新以下文档信息：

- 在“入口清单”中新增日报预览测试命令
- 在“测试策略”中明确 `tests/debug/` 现在覆盖三类调试入口：
  - 连通性检查
  - 手工交易验证
  - 飞书日报预览
- 在“常见问题”或“运行时错误”中补充：
  - 当 `scheduler --once` 因“当日日报已发送”而不再打印报告时，应使用日报预览调试测试

## 7. 执行流程

日报预览调试测试的执行流程固定为：

`读取 config -> 解析目标交易日 -> 连接 MySQL -> 构建共享缓存仓储 -> 构建 report -> 渲染飞书文本 -> print -> 断言最小结构 -> 关闭连接`

其中关键约束如下：

1. 目标交易日优先取环境变量
2. 若未提供环境变量，则回退到 `market_daily_bar` 的最新交易日
3. 报告构建必须复用当前正式分析链路
4. 文本渲染必须复用当前正式飞书文案逻辑
5. 调试测试绝不能调用发送 webhook 的函数

## 8. 伪代码草案

### 8.1 目标

说明如何在不触发飞书发送的前提下，复用正式分析链路生成最新日报文本并打印到终端。

### 8.2 输入

- `config_path`: `config/sim_account.yaml`
- `trade_date_env`: 环境变量 `MARKET_CLOSE_REPORT_TRADE_DATE`
- `dependencies`: `MySQLMarketRepository`、各 analyzer、飞书文本渲染接口

### 8.3 输出

- `printed_text`: 终端中的飞书日报纯文本
- `assertions`: 对标题、日期、核心区块的最小断言

### 8.4 伪代码草案

```python
# [伪代码草案]
# 目标：复用正式市场分析与飞书文案构建逻辑，打印一份“只预览、不发送”的日报文本
# 输入：
# - config_path: 运行时 YAML 配置
# - trade_date_env: 可选环境变量，允许手工指定想复看的交易日
# - repository/analyzers: 正式报告生成依赖
# 输出：
# - printed_text: 打印到终端的飞书纯文本日报
# - assertion_result: 最小结构断言结果，确保输出不是空白或错误文案

def test_market_close_report_preview():
    config = load_runtime_config(config_path)
    repository = MySQLMarketRepository(config.mysql)
    repository.connect()

    try:
        # 1. 先决定目标交易日：优先使用外部显式指定，避免调试历史日报时修改代码
        target_trade_date = resolve_target_trade_date(
            env_value=os.getenv("MARKET_CLOSE_REPORT_TRADE_DATE"),
            fallback=repository.get_latest_trade_date_in_daily_bar(),
        )
        if target_trade_date is None:
            raise AssertionError("market_daily_bar 为空，无法生成日报预览")

        # 2. 报告构建必须沿用正式链路，这样预览结果和正式飞书消息才不会分叉
        cached_repository = CachedMarketDataRepository(repository)
        hot_stock_resolver = HotStockResolver(cached_repository)
        report_builder = MarketCloseReportBuilder(
            cached_repository,
            MarketBreadthAnalyzer(cached_repository),
            MarketProfitEffectAnalyzer(
                cached_repository,
                hot_stock_resolver=hot_stock_resolver,
            ),
            MarketToleranceAnalyzer(
                cached_repository,
                hot_stock_resolver=hot_stock_resolver,
            ),
            MarketEmotionAnalyzer(cached_repository),
        )
        report = report_builder.build(
            target_trade_date,
            config.market_analysis.recent_trade_days,
        )

        # 3. 只调用文案渲染，不调用 webhook 发送，避免调试动作污染外部系统
        text = render_market_close_report_text(report)
        print(text)

        # 4. 最小断言只保证关键结构存在，不把真实市场数值写死成脆弱快照
        assert "市场分析日报" in text
        assert str(target_trade_date) in text
        assert "一眼结论" in text
        assert "最近" in text

    finally:
        # 5. 无论成功失败都必须关闭数据库连接，避免调试测试泄漏连接
        repository.close()
```

## 9. 风险点 / 边界条件

- 若把调试测试继续建立在 `_build_message()` 私有方法之上，后续重构时很容易把测试与生产代码绑定成脆弱实现细节
- 若把该测试放进 `tests/unit/` 或默认门禁，会让无真实配置的开发环境频繁失败
- 若测试断言写死真实市场数值，会导致每天都要改预期，测试失去长期价值
- 若调试测试误调用发送函数，可能造成重复消息或污染业务群

## 10. 验收标准

满足以下条件即视为本次设计落地成功：

- 能执行 `conda run -n stock_analysis pytest tests/debug/test_market_close_report_preview.py -s`
- 终端可看到完整飞书日报纯文本
- 默认不会向飞书发送消息
- 默认不会更新发送 checkpoint
- 可通过环境变量覆盖目标交易日
- `AGENTS.md` 中已有完整入口说明和使用边界
