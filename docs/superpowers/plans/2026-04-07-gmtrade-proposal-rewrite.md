# GMTrade Proposal Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `Proposal/量化交易系统规划书.md` into a first-phase 东方财富掘金仿真实盘最小闭环规划书.

**Architecture:** Replace the current research-platform narrative with a practical execution-system narrative centered on Python and 掘金官方接口. Rewrite the proposal around a four-layer architecture: 基础设施层, 数据接入层, 核心决策层, and 交易执行层. Add a dedicated 测试与质量保障 section and keep the deliverable as a single Markdown proposal.

**Tech Stack:** Markdown, Git, PowerShell, Python-based verification scripts

---

### Task 1: Rewrite Proposal Structure And Content

**Files:**
- Modify: `Proposal/量化交易系统规划书.md`
- Reference: `docs/superpowers/specs/2026-04-07-gmtrade-live-closure-design.md`

- [ ] **Step 1: Inspect the current proposal and the approved rewrite spec**

Run:

```powershell
Get-Content -Path 'D:\Program_python\free_stock\Proposal\量化交易系统规划书.md' -Encoding utf8 -TotalCount 120
Get-Content -Path 'D:\Program_python\free_stock\docs\superpowers\specs\2026-04-07-gmtrade-live-closure-design.md' -Encoding utf8
```

Expected: the current proposal still describes a research-style system, and the spec defines a full rewrite into a 掘金仿真实盘最小闭环 proposal.

- [ ] **Step 2: Rewrite the proposal into the new first-phase execution-system structure**

Replace the document so it includes these sections and content:

```markdown
# 东方财富掘金实盘执行系统规划书（第一期）

## 一、项目定位与边界
- 第一阶段只做掘金仿真环境
- 全部接口统一走东方财富掘金
- 只做自动卖出，不做自动买入
- 自动识别账户全部可卖持仓
- 不做前端、回测、数据库主链路和第二期路线

## 二、总体技术方案
- Python 3.10+
- 东方财富掘金官方接口
- 单进程常驻策略程序
- 本地日志 + 订单回报作为观测手段

## 三、系统架构设计
- 基础设施层
- 数据接入层
- 核心决策层
- 交易执行层

## 四、核心运行链路
1. 启动程序
2. 连接掘金仿真账户
3. 获取账户资金与全部持仓
4. 过滤可卖持仓
5. 逐标的判断止盈止损
6. 检查未完成卖单
7. 触发卖出委托
8. 接收回报并更新状态
9. 记录日志并继续运行

## 五、模块设计说明
- 掘金接入模块
- 持仓与状态模块
- 卖出策略模块
- 订单执行模块
- 调度与日志模块

## 六、测试与质量保障
- 单元测试：止盈止损判断、交易时段判断、防重复卖单
- 集成测试：持仓读取、状态更新、信号触发到委托执行链路
- 仿真冒烟验证：掘金仿真账户下的最小自动卖出闭环

## 七、里程碑设计
- M0 环境与账户连通
- M1 数据接入跑通
- M2 核心决策与状态管理
- M3 自动卖出执行闭环
- M4 测试、日志与稳定运行

## 八、风险与运行约束
- 仿真与真实交易差异
- 重复卖单风险
- 多标的状态串扰风险
- 行情和回报异常
- 交易时段控制
- 自动买入不在范围内
```

Expected: the rewritten proposal is fully centered on the first-phase 掘金 execution loop, uses the four-layer architecture, and no longer reads as a research platform document.

- [ ] **Step 3: Save the Markdown rewrite with standard GitHub-friendly formatting**

Use:

```powershell
Get-Content -Path 'D:\Program_python\free_stock\Proposal\量化交易系统规划书.md' -Encoding utf8 -TotalCount 80
```

Expected: clean Markdown headings, lists, and tables without Obsidian callouts or stale research-platform sections.

### Task 2: Verify Rewrite Consistency

**Files:**
- Verify: `Proposal/量化交易系统规划书.md`

- [ ] **Step 1: Check that old first-phase research keywords are removed or replaced**

Run:

```powershell
rg -n "前端展示层|回测引擎|新浪|AkShare|ECharts|Backtrader|第二期|远期路线" 'D:\Program_python\free_stock\Proposal\量化交易系统规划书.md'
```

Expected: no stale core narrative remains about front-end, backtesting, or old data-source architecture, except where explicitly listed as out-of-scope.

- [ ] **Step 2: Check that the new GMTrade execution keywords are present**

Run:

```powershell
rg -n "东方财富掘金|仿真账户|自动卖出|全部持仓|重复卖单|交易时段|Python|基础设施层|数据接入层|核心决策层|交易执行层|测试与质量保障" 'D:\Program_python\free_stock\Proposal\量化交易系统规划书.md'
```

Expected: the proposal clearly states the new execution environment, sell-only scope, multi-symbol handling, four-layer architecture, testing section, and runtime safeguards.

- [ ] **Step 3: Run a strict validation script against the rewritten proposal**

Run:

```powershell
$file = Get-ChildItem -Path 'D:\Program_python\free_stock\Proposal' -Filter '*.md' | Select-Object -First 1 -ExpandProperty FullName
$text = Get-Content -LiteralPath $file -Raw -Encoding UTF8
$checks = [ordered]@{
  has_gmtrade_title = $text.Contains('东方财富掘金实盘执行系统规划书（第一期）')
  has_python = $text.Contains('Python')
  has_simulation = $text.Contains('仿真账户')
  has_sell_only = $text.Contains('只做自动卖出')
  has_multi_symbol = $text.Contains('全部持仓')
  has_duplicate_order_guard = $text.Contains('重复卖单')
  has_infra_layer = $text.Contains('基础设施层')
  has_data_access_layer = $text.Contains('数据接入层')
  has_core_decision_layer = $text.Contains('核心决策层')
  has_execution_layer = $text.Contains('交易执行层')
  has_testing_section = $text.Contains('测试与质量保障')
  no_frontend_mainline = (-not $text.Contains('前端展示层'))
}
$checks.GetEnumerator() | ForEach-Object { Write-Output ($_.Key + '=' + $_.Value) }
if ($checks.Values -contains $false) { exit 1 }
```

Expected: every check prints `True` and the command exits with code `0`.

- [ ] **Step 4: Review the final diff**

Run:

```powershell
git diff -- 'Proposal/量化交易系统规划书.md'
```

Expected: the diff shows a full rewrite from research-system planning to first-phase 掘金 execution-system planning.
