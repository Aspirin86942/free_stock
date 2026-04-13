# M4 测试、日志与稳定运行设计

## 1. 目标

M4 的目标不是扩展新的交易能力，而是把当前已经完成的 `M0`、`M1`、`M2`、`M3` 收敛成一套可交付、可回归、可审计的运行基线。

本次设计只解决两类问题：

- 如何证明系统在本地开发机上具备稳定、可重复的质量门禁
- 如何让一笔自动卖单从“进入执行链”到“进入终态”的全过程可以被日志和审计数据直接追踪

完成后的 M4 应满足：

- 默认质量门禁可在本地无掘金终端条件下执行
- 真实仿真链路有明确的手工 smoke 清单和通过标准
- `M3` 每轮运行有稳定轮次日志
- 每笔自动卖单有完整审计链，并能直接得到毫秒级终态耗时

## 2. 范围与非范围

### 2.1 范围

- 新增静态检查门禁：`ruff`
- 新增本地假数据 smoke 测试分层
- 规范化真实仿真 smoke 清单
- 强化 `runtime.log` 的轮次级运行日志
- 新增 `order_audit.log` 订单审计日志
- 为 `M3` 执行态补充提交和终态时间字段
- 在 CLI 结构化输出中投影终态耗时字段

### 2.2 非范围

- 不新增交易策略
- 不重写 `M3` 执行主链
- 不引入数据库或外部监控平台
- 不做日志轮转、日志上传或告警平台接入
- 不做多账户、多进程、多策略扩展
- 不把自动买入纳入自动执行主线

## 3. 当前基线与缺口

当前仓库已经具备以下基础：

- [main.py](/D:/Program_python/free_stock/main.py) 已具备 `m0`、`m1`、`m2`、`m3` 模式入口
- [bootstrap.py](/D:/Program_python/free_stock/src/gmtrade_live/bootstrap.py) 已输出结构化 JSON 摘要
- [logging_setup.py](/D:/Program_python/free_stock/src/gmtrade_live/logging_setup.py) 已建立 `runtime.log`
- `tests/unit` 与 `tests/integration` 已覆盖主要业务链路
- [query_smoke_test.py](/D:/Program_python/free_stock/scripts/query_smoke_test.py) 已提供真实查询驱动 smoke 脚本

当前缺口集中在三处：

1. 缺少统一静态检查门禁，代码风格和基础质量没有被自动化约束
2. 缺少“默认可执行”的本地 smoke 层，日常回归只能依赖 unit/integration 或人工执行真实链路
3. 缺少结构化订单审计日志，无法稳定回答“一笔单从提交受理到终态花了多少毫秒”

## 4. 核心设计决定

### 4.1 M4 只收口，不扩边界

M4 不再新增任何交易能力，不修改 `M2` 的观察型 dry-run 定位，也不改变 `M3` 的真实执行边界。

M4 只做质量门禁与观测补强：

- 让默认回归入口更完整
- 让真实仿真验证更规范
- 让运行日志和订单审计更可复盘

### 4.2 测试分成默认门禁和手工仿真两层

默认门禁必须满足两个约束：

- 不依赖掘金终端
- 开发机上任何时候都能执行

因此默认门禁固定为：

```powershell
conda run -n stock_analysis ruff check .
conda run -n stock_analysis pytest tests/unit
conda run -n stock_analysis pytest tests/integration
conda run -n stock_analysis pytest tests/smoke
```

真实仿真 smoke 保留为手工验证，不进入默认门禁。原因很直接：

- 它依赖掘金终端、仿真账户和盘中状态
- 账户是否有仓、是否满足触发条件都不是稳定的本地前提
- 把它绑进默认门禁会让回归结果被外部环境污染

### 4.3 真实仿真 smoke 沿用现有入口，不另造体系

真实仿真 smoke 不是新系统，而是把现有入口收敛成一份可执行清单：

- `M0`：`conda run -n stock_analysis python main.py --config config/sim_account.yaml`
- `M1`：`conda run -n stock_analysis python main.py --config config/sim_account.yaml --mode m1 ...`
- `M1` 查询链路脚本：[query_smoke_test.py](/D:/Program_python/free_stock/scripts/query_smoke_test.py)
- `M2`：`conda run -n stock_analysis python main.py --config config/sim_account.yaml --mode m2 --once`
- `M3`：`conda run -n stock_analysis python main.py --config config/sim_account.yaml --mode m3 --once`
  - `--reconcile-timeout-seconds` 为可选参数
  - 默认值为 `5`
  - 只有在需要覆盖默认收口预算时才显式传入，例如 `--reconcile-timeout-seconds 7`

M4 要求不是“真实链路每次都跑”，而是：

- 手工 smoke 有明确入口
- 每一步有明确通过标准
- 因外部条件不能执行时必须记录未执行原因

### 4.4 日志拆成运行日志和订单审计日志两条线

单一 `runtime.log` 适合观察程序运行节奏和异常，但不适合承载订单级毫秒审计。M4 采用两条日志线：

- `runtime.log`
  - 面向运行观察
  - 保留文本日志格式
  - 重点表达轮次、异常、超时、状态迁移

- `order_audit.log`
  - 面向订单审计
  - 采用 JSON Lines
  - 每条记录对应单笔订单的关键生命周期事件或终态汇总

这样的拆分可以避免两个问题：

- 不再需要从自由文本里硬解析毫秒指标
- 不把高频状态变化和订单终态证据混在一起，降低排障噪音

### 4.5 终态耗时以“受理成功到终态”为唯一主指标

本次唯一强制指标为：

- `order_terminal_latency_ms = terminal_state_at - submit_accepted_at`

终点限定为订单进入明确终态：

- `filled`
- `cancelled`
- `failed`

这里不把“首次成交耗时”纳入 M4 强制范围。原因：

- 用户当前核心诉求是“每次下单到成交的毫秒数”
- 现阶段自动卖出闭环更关注“这笔单最终收口花了多久”
- 首次成交耗时在部分成交场景下有价值，但属于后续扩展指标，不应把 M4 范围继续拉宽

### 4.6 稳定运行语义延续现状，不做激进自愈

`M2` 与 `M3` 的异常行为继续沿用当前边界：

- `M2`
  - 单轮异常输出结构化错误
  - 记录错误日志
  - 连续模式允许下一轮继续执行

- `M3`
  - 单轮异常立即中止
  - 输出 `m3_round_error`
  - 避免在未知执行态下继续自动卖出

M4 的职责是把这套语义测试化和文档化，不是把 `M3` 改成自动恢复继续发单。

## 5. 文件与职责设计

### 5.1 配置与工具

- 修改 [pyproject.toml](/D:/Program_python/free_stock/pyproject.toml)
  - 增加 `ruff` 依赖和基础规则配置
  - 保留现有 `pytest` 配置

### 5.2 日志初始化

- 修改 [logging_setup.py](/D:/Program_python/free_stock/src/gmtrade_live/logging_setup.py)
  - 保留 `runtime.log` handler
  - 增加 `order_audit.log` 专用 logger 或 handler 构造能力
  - 明确 UTF-8 编码

### 5.3 M3 执行态

- 修改 [m3_state_manager.py](/D:/Program_python/free_stock/src/gmtrade_live/services/m3_state_manager.py)
  - 在 `M3ExecutionStateSnapshot` 新增时间字段：
    - `submit_started_at`
    - `submit_accepted_at`
    - `terminal_state_at`
  - 这些字段只表达执行时间事实，不承载新的业务决策语义

### 5.4 M3 编排与对外投影

- 修改 [m3_execution_service.py](/D:/Program_python/free_stock/src/gmtrade_live/services/m3_execution_service.py)
  - 在提交和收口阶段维护时间字段
  - 在进入终态时计算 `order_terminal_latency_ms`
  - 生成订单审计事件

- 修改 [models.py](/D:/Program_python/free_stock/src/gmtrade_live/models.py)
  - 为 `M3ExecutionDetail` 增加时间和终态耗时字段

- 修改 [bootstrap.py](/D:/Program_python/free_stock/src/gmtrade_live/bootstrap.py)
  - 在 `m3_execution_detail` JSON 输出中补充：
    - `submit_accepted_at`
    - `terminal_state_at`
    - `order_terminal_latency_ms`
  - 在轮次开始、结束、异常时输出标准化运行日志

### 5.5 测试

- 新增 `tests/smoke/`
  - 本地假数据 smoke 测试

- 修改现有单测与集成测试
  - `test_runtime.py`
  - `test_bootstrap.py`
  - `test_m3_state_manager.py`
  - `test_m3_execution_service.py`
  - 必要时补充 `test_main.py`

### 5.6 真实 smoke 文档

- 新增或更新 `docs/superpowers/specs/` 下的验证说明文档
  - 记录手工仿真 smoke 清单
  - 记录未执行原因和验证证据要求

## 6. 测试设计

### 6.1 默认质量门禁

默认门禁固定为四层：

1. `ruff`
2. `tests/unit`
3. `tests/integration`
4. `tests/smoke`

它们的职责分别是：

- `ruff`
  - 静态规则、导入、基础风格和明显错误

- `tests/unit`
  - 纯逻辑、纯模型、状态机、字段投影

- `tests/integration`
  - 多模块拼装链路

- `tests/smoke`
  - 从入口跑通一条最小闭环，证明“系统能跑”

### 6.2 本地假数据 smoke

本地 smoke 必须基于假网关或桩对象，不依赖掘金终端。

建议至少覆盖：

- `m2` smoke
  - 从 CLI 或 bootstrap 入口跑一轮
  - 断言输出 `m2_round_summary`
  - 断言生成 `runtime.log`

- `m3` smoke
  - 跑一轮可进入终态的假数据自动卖出链路
  - 断言输出 `m3_round_summary`
  - 断言输出 `m3_execution_detail`
  - 断言生成 `runtime.log`
  - 断言生成 `order_audit.log`
  - 断言审计数据里存在 `order_terminal_latency_ms`

这里本地 smoke 必须进入 `pytest`，而不是单独脚本。原因：

- 能直接纳入默认门禁
- 失败时有统一断言证据
- 可以和现有单测、集成测试共享临时目录与桩对象

### 6.3 真实仿真 smoke

真实仿真 smoke 仍按现有仓库入口执行，但需要补齐通过标准：

- `M0`
  - 能连接账户
  - 能读取资金、持仓、行情

- `M1`
  - 能提交一笔手工委托
  - 能通过查单与查成交确认结果

- `M2`
  - 至少输出一轮 `m2_round_summary`

- `M3`
  - 若存在可触发标的，则应能完成自动卖出并输出查询驱动收口结果
  - 若无触发条件，必须记录未执行原因

### 6.4 失败证据要求

M4 要求所有验证都能留下至少一种证据：

- 测试命令
- 终端输出摘要
- 日志文件路径
- 未执行原因

不得用“应该没问题”或“环境不方便测”替代证据记录。

## 7. 日志与审计设计

### 7.1 `runtime.log`

`runtime.log` 继续使用文本日志，但事件名应标准化。至少包含：

- `round_started`
- `round_completed`
- `round_failed`
- `round_overrun`
- `state_change`
- `gateway_error`

建议关键字段：

- `mode`
- `round`
- `session_state`
- `position_count`
- `candidate_count`
- `submitted_count`
- `open_order_count`
- `duration_ms`
- `error_code`
- `error_type`
- `retryable`

`retryable` 的规则：

- 若异常是 `ServiceError`，使用其自身 `retryable`
- 若不是结构化业务错误，则记为未知，不臆测可重试性

### 7.2 `order_audit.log`

`order_audit.log` 采用 JSON Lines，每行一条独立审计记录，默认 UTF-8。

建议最小字段集合：

- `event_type`
- `mode`
- `round_no`
- `account_id`
- `symbol`
- `cl_ord_id`
- `broker_order_id`
- `decision_trigger_reason`
- `decision_block_reason`
- `execution_state`
- `last_order_status`
- `requested_volume`
- `filled_volume`
- `remaining_volume`
- `avg_price`
- `message`
- `submit_started_at`
- `submit_accepted_at`
- `terminal_state_at`
- `order_terminal_latency_ms`

### 7.3 订单审计事件类型

本次不引入复杂事件总线，只定义最小可审计事件类型：

- `quantity_blocked`
- `submit_rejected`
- `submit_accepted`
- `order_state_updated`
- `terminal_state_reached`
- `reconcile_timeout`

其中：

- `terminal_state_reached` 必须带 `order_terminal_latency_ms`
- `reconcile_timeout` 不是失败语义，只表达“本轮预算耗尽但订单尚未终态”

### 7.4 M3 时间字段更新规则

时间字段按以下规则写入：

- `submit_started_at`
  - 进入 `submitting` 前后写入

- `submit_accepted_at`
  - 只有柜台同步接受且 `cl_ord_id` 存在时写入

- `terminal_state_at`
  - 执行态首次进入 `filled`、`cancelled`、`failed` 时写入
  - 一旦写入，不允许被后续非终态覆盖

这样可以保证终态耗时稳定可复算，不会被后续查询噪音改坏。

### 7.5 CLI 字段投影

`m3_execution_detail` 在现有字段基础上新增：

- `submit_accepted_at`
- `terminal_state_at`
- `order_terminal_latency_ms`

输出规则：

- 若订单尚未进入终态，则 `order_terminal_latency_ms = null`
- 若订单未被同步接受，则 `submit_accepted_at = null`
- CLI 只是对外投影，不替代 `order_audit.log` 作为唯一审计源

## 8. 稳定运行与错误处理

### 8.1 M2

`M2` 维持观察型语义：

- 单轮失败写日志
- 输出结构化错误
- 连续模式可继续下一轮

这保证 dry-run 在行情缺失、查询异常等场景下仍可作为观察工具继续工作。

### 8.2 M3

`M3` 维持真实执行链语义：

- 单轮异常立即终止
- 不在不确定状态下继续发单
- 通过日志和结构化错误保留现场

这符合当前项目“正确性优先于连续性”的边界。

### 8.3 超时与失败的区分

必须明确区分三类状态：

- 已终态
  - `filled`
  - `cancelled`
  - `failed`

- 本轮预算耗尽但仍未终态
  - 不是失败
  - 记录 `reconcile_timeout`
  - 由下一轮继续跟踪

- 服务级异常中止
  - 记 `round_failed`
  - 输出结构化错误
  - `M3` 直接退出

如果不区分这三类状态，日志会同时误导运行判断和订单复盘。

## 9. 完成定义

M4 视为完成，至少需要同时满足以下条件：

- 默认质量门禁可执行并通过
  - `ruff`
  - `tests/unit`
  - `tests/integration`
  - `tests/smoke`

- 真实仿真 smoke 有明确执行清单与通过标准
- `runtime.log` 能稳定表达轮次开始、结束、异常和超时
- `order_audit.log` 能按 `symbol + cl_ord_id` 追出完整订单关键节点
- 进入终态的订单能直接得到 `order_terminal_latency_ms`
- 未执行的真实仿真步骤必须明确记录原因

## 10. 风险与控制

### 10.1 风险：日志字段膨胀

若把所有上下文字段都塞进 `runtime.log`，文本日志会变成难以阅读的混合载体。

控制方式：

- `runtime.log` 只保留运行视角
- 订单细节统一进入 `order_audit.log`

### 10.2 风险：把真实 smoke 绑进默认门禁

这会让日常回归结果依赖盘中环境和账户状态，导致门禁不稳定。

控制方式：

- 真实 smoke 保持手工验证
- 默认门禁只使用本地可重复条件

### 10.3 风险：终态耗时被重复覆盖

若终态字段没有写入规则，后续轮询可能把已经确定的终态时间改坏。

控制方式：

- `terminal_state_at` 只在首次进入终态时写入
- 后续非终态更新不得覆盖

## 11. 验收建议

M4 落地后，建议按以下顺序验证：

1. 本地执行默认门禁
2. 检查 `tests/smoke` 能生成本地日志与终态耗时
3. 用仿真环境执行 `M0`、`M1`、`M2`
4. 在具备触发条件时执行 `M3`
5. 归档验证命令、输出摘要与日志文件位置

这样既能覆盖开发机回归，也能覆盖真实环境闭环。
