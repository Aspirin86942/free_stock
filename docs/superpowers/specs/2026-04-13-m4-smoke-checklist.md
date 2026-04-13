# M4 真实仿真 Smoke Checklist

## 1. 文档目标

本文定义 `M4` 阶段的真实仿真 smoke 清单、通过标准、证据要求与未执行记录方式。

`M4` 的职责是把现有 `M0`、`M1`、`M2`、`M3` 的运行语义测试化和文档化，不新增 `--mode m4`，也不把 `M3` 改成自动恢复继续发单。

## 2. 适用范围

本文只用于真实仿真环境下的手工 smoke。

它不替代默认本地门禁，也不进入默认自动化回归。

默认自动化门禁仍然是：

```powershell
conda run -n stock_analysis ruff check .
conda run -n stock_analysis pytest tests/unit
conda run -n stock_analysis pytest tests/integration
conda run -n stock_analysis pytest tests/smoke
```

## 3. 执行前提

执行真实仿真 smoke 前，必须满足以下前提：

- 已启动掘金终端，且 `gmtrade_endpoint` 指向本地终端，例如 `127.0.0.1:7001`
- 使用 `config/sim_account.yaml`
- 优先使用常规 A 股仿真账户，不把 `7x24` 技术账户结果误记为正规交易日结果
- 执行环境统一使用 `conda run -n stock_analysis ...`
- 若要验证 `M3`，账户内必须有可卖持仓，且该持仓满足策略触发条件

交易日约束必须写清楚：

- 对常规 A 股仿真账户，非交易日不应把 `M2/M3` 盘中行为记为 smoke 通过
- 例如 `2026-04-11` 对常规交易日账户应视为非交易日
- 若 `2026-04-11` 在 `7x24` 技术账户上跑通，只能证明技术链路可用，不能作为常规交易日账户的正式 smoke 证据

## 4. 执行顺序

真实仿真 smoke 按以下顺序执行：

1. `M0` 连通性
2. `M1` 手工交易闭环
3. `M1` 查询链路脚本
4. `M2` 单轮 dry-run
5. `M3` 单轮自动卖出

原因很直接：

- 先确认连接和基础查询正常
- 再确认手工下单和主动查询闭环正常
- 最后再验证 `M2/M3` 的策略与执行链

## 5. 检查项与通过标准

### 5.1 `M0` 连通性

命令：

```powershell
conda run -n stock_analysis python main.py --config config/sim_account.yaml
```

通过标准：

- 命令退出码为 `0`
- CLI 输出包含 `account_id`
- CLI 输出包含 `available_cash`
- CLI 输出包含 `position_count`
- CLI 输出包含 `quote_count`

证据要求：

- 保存命令与执行时间
- 保存 CLI 输出摘要
- 保存对应 `runtime.log`

### 5.2 `M1` 手工交易闭环

建议先在仿真环境做一笔最小交易量验证。

卖出命令示例：

```powershell
conda run -n stock_analysis python main.py --config config/sim_account.yaml --mode m1 `
  --side sell --symbol SHSE.600839 --volume 100 --price-type market --timeout-seconds 60
```

买入命令示例：

```powershell
conda run -n stock_analysis python main.py --config config/sim_account.yaml --mode m1 `
  --side buy --symbol SHSE.600839 --volume 100 --price-type limit --price 10.50 `
  --timeout-seconds 120
```

通过标准：

- 命令退出码为 `0`
- CLI 输出 `verification_passed=true`
- 输出中存在 `submit_accepted`
- 输出中存在最终 `last_order_status`
- 若有成交，输出中存在 `filled_volume` 与 `avg_price`

证据要求：

- 保存 CLI 输出
- 保存 `runtime.log`
- 记录使用的是买单还是卖单

### 5.3 `M1` 查询链路脚本

命令：

```powershell
conda run -n stock_analysis python scripts/query_smoke_test.py --config config/sim_account.yaml
```

通过标准：

- 脚本退出码为 `0`
- 能完成“提交结果 + 主动查单 + 主动查成交”的最小闭环
- 不依赖供应商 callback 才能判定通过

证据要求：

- 保存脚本输出
- 记录对应的 `cl_ord_id`
- 若失败，记录失败发生在提交、查单还是查成交阶段

### 5.4 `M2` 单轮 dry-run

命令：

```powershell
conda run -n stock_analysis python main.py --config config/sim_account.yaml --mode m2 --once
```

通过标准：

- 命令退出码为 `0`
- CLI 输出中存在 `m2_round_summary`
- 轮次日志中存在标准化开始/结束记录
- 不发生静默失败

证据要求：

- 保存 CLI 输出
- 保存 `runtime.log`
- 若处于非交易日或收盘后，必须记录会话态与对应解释

### 5.5 `M3` 单轮自动卖出

命令：

```powershell
conda run -n stock_analysis python main.py --config config/sim_account.yaml --mode m3 --once
```

可选命令：

```powershell
conda run -n stock_analysis python main.py --config config/sim_account.yaml --mode m3 --once `
  --reconcile-timeout-seconds 7
```

说明：

- `--reconcile-timeout-seconds` 是可选参数
- 默认值为 `5`
- 只有在需要覆盖默认收口预算时才显式传入

通过标准：

- 命令退出码为 `0`
- CLI 输出中存在 `m3_round_summary`
- 至少一个 `m3_execution_detail` 暴露 `submit_accepted_at`
- 若订单进入终态，至少一个 `m3_execution_detail` 暴露 `terminal_state_at`
- 若订单进入终态，至少一个 `m3_execution_detail` 暴露 `order_terminal_latency_ms`
- `order_audit.log` 至少包含 `submit_accepted`
- 若订单进入终态，`order_audit.log` 至少包含 `terminal_state_reached`
- `runtime.log` 中存在标准化轮次日志

补充说明：

- 若 `M3` 轮次因账户无仓、无可卖仓或未触发策略而未发单，不记为失败，但必须明确记录“未满足发单前提”
- 若发生异常，`M3` 应按既有语义立即中止，不继续下一轮
- 本文不要求 `M3` 具备自动恢复继续发单能力

证据要求：

- 保存 CLI 输出
- 保存 `runtime.log`
- 保存 `order_audit.log`
- 记录本次使用的标的、数量、最终状态与 `order_terminal_latency_ms`

## 6. 未执行与阻断记录

真实仿真 smoke 允许出现“未执行”，但不允许空白带过。

每个未执行项都必须至少记录以下字段：

- 检查项名称
- 日期与时间
- 账户类型
- 未执行原因
- 是否需要补跑
- 补跑前置条件

推荐模板：

```text
检查项: M3 单轮自动卖出
执行时间: 2026-04-13 10:35:00 Asia/Shanghai
账户类型: 常规 A 股仿真账户
结果: 未执行
原因: 账户无可卖持仓，无法触发自动卖出
是否补跑: 是
补跑前置条件: 先准备满足触发条件的仿真持仓
```

## 7. 结果判定

建议使用以下三态记录 smoke 结果：

- `通过`
- `失败`
- `未执行`

判定规则：

- `M0`、`M1`、`M1` 查询链路、`M2` 若已执行且满足通过标准，记为 `通过`
- `M3` 只有在满足发单前提时才要求给出正式通过或失败结论
- 因外部条件不成立而未执行时，必须记为 `未执行`，不能写成“默认通过”

## 8. 证据归档建议

每次真实仿真 smoke，至少归档以下证据：

- 执行日期
- 账户类型
- 执行命令
- CLI 输出
- `runtime.log`
- `order_audit.log`（若执行了 `M3`）
- 关键 `cl_ord_id` / `broker_order_id`
- 失败或未执行原因

若后续切换到常规交易日账户，建议把首轮正式 smoke 单独标记为“常规交易日账户基线验证”，与此前 `7x24` 技术账户结果分开保存。

## 9. Execution Record

以下记录对应本次 `M4` 落地收口时的实际执行情况，更新时间为 `2026-04-13`。

### 9.1 Default Gate

| Step | Executed | Result | Evidence | Not Executed Reason |
| --- | --- | --- | --- | --- |
| `ruff check .` | Yes | Passed | `conda run -n stock_analysis ruff check .` -> `All checks passed!` | |
| `pytest tests/unit -q` | Yes | Passed | `conda run -n stock_analysis pytest tests/unit -q` -> `119 passed` | |
| `pytest tests/integration -q` | Yes | Passed | `conda run -n stock_analysis pytest tests/integration -q` -> `6 passed` | |
| `pytest tests/smoke -q` | Yes | Passed | `conda run -n stock_analysis pytest tests/smoke -q` -> `2 passed` | |

### 9.2 Real Simulation Smoke

| Step | Executed | Result | Evidence | Not Executed Reason |
| --- | --- | --- | --- | --- |
| `M0` | No | Not Executed | | 本次会话未连接真实掘金终端，也未在当前工作树内留存可复核的常规交易日账户执行证据。历史上 `7x24` 技术账户的跑通结果不计入本表。 |
| `M1` | No | Not Executed | | 本次会话未进行真实仿真手工下单；缺少可复核的常规交易日账户、柜台可用性与当下下单窗口证据。 |
| `M1` 查询链路脚本 | No | Not Executed | | 本次会话未对真实仿真账户执行 `scripts/query_smoke_test.py`；无实时 `cl_ord_id`、查单与查成交证据。 |
| `M2` | No | Not Executed | | 本次会话未对真实仿真账户执行 `--mode m2 --once`；常规交易日账户的盘中会话态与行情条件未现场确认。 |
| `M3` | No | Not Executed | | 本次会话未对真实仿真账户执行 `--mode m3 --once`；未现场确认常规交易日账户、可卖持仓和触发条件。 |

### 9.3 Follow-up Requirement

当切换到常规交易日账户并具备真实柜台条件后，必须补跑 `M0`、`M1`、`M1` 查询链路脚本、`M2`、`M3`，并把 CLI 输出、`runtime.log`、`order_audit.log` 与未执行原因更新到本节表格中。
