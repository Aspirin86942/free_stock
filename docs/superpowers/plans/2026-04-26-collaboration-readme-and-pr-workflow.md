# Collaboration README And PR Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为新协作者补齐根目录 `README.md`、`CONTRIBUTING.md` 和 GitHub PR 模板，固定 `main/dev/feature/*` 协作流程并把关键风险提示收口到文档入口。

**Architecture:** 先新增根目录 `README.md`，把仓库用途、环境前提、常用命令和文档索引收口成协作者第一入口。再新增 `CONTRIBUTING.md` 固定分支模型、开发流程、测试义务和禁止事项，最后创建 `.github/pull_request_template.md`，把 PR 规范变成默认动作而不是口头约定。

**Tech Stack:** Markdown, Git, GitHub pull request templates, PowerShell, conda (`stock_analysis`)

---

## File Structure

- Create: `README.md`
  - 面向协作者的根目录上手入口，解释项目概览、环境前提、快速开始、常用命令、目录结构、协作摘要和文档索引。
- Create: `CONTRIBUTING.md`
  - 面向开发者的协作规范，固定 `main/dev/feature/*` 分支模型、提交流程、测试要求、文档同步规则和禁止事项。
- Create: `.github/pull_request_template.md`
  - GitHub PR 默认模板，要求每次 PR 说明问题、改动点、影响范围、验证方式、外部依赖影响和回滚方案。

### Task 1: 新增协作者上手 README

**Files:**
- Create: `README.md`

- [ ] **Step 1: 写入 `README.md` 首稿**

```markdown
# 东方财富掘金实盘执行系统（free_stock）

> 面向协作者的仓库上手入口。第一次进入仓库先看这里，开始开发前再看 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 项目概览

本仓库当前包含两条独立但共享基础设施的链路：

### 1. 自动交易链路（`main.py trade`）

- 目标：在掘金仿真账户中完成“持仓识别 -> 规则判断 -> 自动卖出 -> 回报收口 -> 日志审计”的最小闭环
- 当前约束：只做自动卖出，不做自动买入
- 入口：`conda run -n stock_analysis python main.py trade --config config/sim_account.yaml`

### 2. 市场分析链路（`main.py scheduler`）

- 目标：完成“官方日线补数 -> MySQL -> 最近 10 个交易日盘后分析 -> 飞书推送”的完整链路
- 当前约束：依赖本地掘金终端、MySQL 和飞书 webhook
- 入口：`conda run -n stock_analysis python main.py scheduler --config config/sim_account.yaml --once`

## 开发环境与外部依赖

- Python `3.10+`
- conda 环境：`stock_analysis`
- 掘金终端：本地 `127.0.0.1:7001`
- MySQL：市场分析链路需要
- 飞书 webhook：盘后日报发送需要

> 注意：
> - `config/sim_account.yaml` 是本地私有配置，不可提交
> - `gm.token`、MySQL 密码、飞书 webhook 不要出现在 PR、issue、截图或录屏里
> - `tests/debug/` 是显式运行的真实环境调试入口，不属于默认 `pytest` 回归门禁

## 快速开始

1. 安装项目

```bash
conda run -n stock_analysis python -m pip install -e .
```

2. 准备本地配置

- 参考 `config/sim_account.example.yaml` 新建 `config/sim_account.yaml`
- 至少填写 `gm`、`trade`、`market_analysis`、`mysql`、`feishu`、`scheduler`

3. 验证 CLI 可用

```bash
conda run -n stock_analysis python main.py -h
```

4. 运行一个安全的单元测试

```bash
conda run -n stock_analysis pytest tests/unit/test_config.py -q
```

## 常用命令

### 本地安全命令（不触达真实外部系统）

```bash
conda run -n stock_analysis python main.py -h
conda run -n stock_analysis pytest tests/unit/test_config.py -q
conda run -n stock_analysis pytest
```

### 只读或低风险调试（会连接真实服务，但不自动卖出）

```bash
conda run -n stock_analysis python observe_decisions.py --config config/sim_account.yaml --once
conda run -n stock_analysis python tools/debug/check_connectivity.py --config config/sim_account.yaml
conda run -n stock_analysis pytest tests/debug/test_market_close_report_preview.py -s
```

### 会写数据库或发送外部消息

```bash
conda run -n stock_analysis python main.py scheduler --config config/sim_account.yaml --once
```

### 可能触发真实交易指令

```bash
conda run -n stock_analysis python main.py trade --config config/sim_account.yaml
conda run -n stock_analysis python tools/debug/manual_trade.py --config config/sim_account.yaml --side sell --symbol SHSE.600839 --volume 100 --price-type market --timeout-seconds 60
```

## 项目结构

```text
src/gmtrade_live/          核心业务代码
tests/unit/                默认单元测试
tests/integration/         依赖掘金终端的集成测试
tests/debug/               显式运行的真实环境调试测试
tools/debug/               手工排障脚本
config/                    配置示例与本地配置入口
docs/                      运行说明、设计 spec、实现 plan
```

## 协作流程摘要

1. 从最新 `dev` 创建 `feature/*`、`fix/*`、`docs/*` 或 `refactor/*`
2. 在功能分支完成代码、测试和文档同步
3. 提 PR 回 `dev`
4. 合并方式统一使用 `Squash and merge`
5. `dev` 稳定后，再由维护者发起 `dev -> main` 的 PR

完整协作规则见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 文档索引

- 自动交易运行说明：[`docs/auto-sell-runtime.md`](docs/auto-sell-runtime.md)
- 市场分析运行说明：[`docs/market-analysis-runtime.md`](docs/market-analysis-runtime.md)
- 系统规划书：[`docs/Proposal/量化交易系统规划书.md`](docs/Proposal/量化交易系统规划书.md)
- 设计 spec：[`docs/superpowers/specs/`](docs/superpowers/specs/)
- 实现 plan：[`docs/superpowers/plans/`](docs/superpowers/plans/)

## 注意事项

- 默认 conda 环境统一写 `stock_analysis`，不要在公共文档里混用其他环境名
- `main` 不是日常开发分支，日常协作统一走 `dev -> feature/* -> PR -> dev`
- 真实环境命令执行前，先确认它会不会发单、写数据库或发送飞书消息
- 修改命令、配置、流程或外部依赖口径时，记得同步更新文档
```

- [ ] **Step 2: 检查 README 关键章节是否齐全**

Run: `rg -n "快速开始|常用命令|项目结构|协作流程摘要|文档索引|注意事项" README.md`

Expected: 输出包含以上 6 个章节标题，说明 README 结构完整，没有漏掉入口、协作或风险提示。

- [ ] **Step 3: 检查 README 是否写明环境、配置和真实环境风险**

Run: `rg -n "stock_analysis|config/sim_account.yaml|tests/debug|main.py trade|main.py scheduler|飞书 webhook" README.md`

Expected: 输出能看到统一环境名、私有配置告警、`tests/debug/` 语义、交易入口、调度入口和飞书依赖提示。

- [ ] **Step 4: 复查 README diff，确认只包含新协作者入口内容**

Run: `git diff -- README.md`

Expected: diff 只新增 `README.md`，内容集中在上手说明、命令分类、协作摘要和文档索引，没有混入与本次任务无关的改动。

- [ ] **Step 5: 提交 README**

```bash
git add README.md
git commit -m "docs: add collaborator onboarding README"
```

### Task 2: 新增协作规范 CONTRIBUTING

**Files:**
- Create: `CONTRIBUTING.md`

- [ ] **Step 1: 写入 `CONTRIBUTING.md` 首稿**

```markdown
# Contributing Guide

本仓库当前按“两人协作、`dev` 集成、`feature/*` 开发、`main` 稳定发布”的方式维护。

> 当前仓库即使还没有配置 GitHub Branch Protection，也默认按下面的规则手动执行，不把 `main` 或 `dev` 当作随手直推的开发分支。

## 分支模型

- `main`
  - 只接收稳定版本
  - 不作为日常开发分支
- `dev`
  - 日常集成分支
  - 所有功能、修复、文档改动默认先合到这里
- `feature/*`、`fix/*`、`docs/*`、`refactor/*`
  - 一次改动一个分支
  - 统一从最新 `dev` 创建
  - 完成后通过 PR 合回 `dev`

## 标准开发流程

1. 同步远端 `dev`

```bash
git fetch origin
git checkout dev
git pull origin dev
```

2. 创建功能分支

```bash
git checkout -b feature/market-close-summary
```

3. 在功能分支完成改动

- 运行与改动直接相关的测试
- 如果改动了命令、配置、运行方式或协作流程，同步更新文档
- 不把不相关的顺手修改塞进同一个分支

4. 推送分支并发起 PR

```bash
git push -u origin feature/market-close-summary
```

- PR 目标分支默认是 `dev`
- 合并方式统一用 `Squash and merge`

5. 发布到 `main`

- 当 `dev` 上一批改动已经验证稳定后，再由维护者发起 `dev -> main` 的 PR
- 不从个人 `feature/*` 分支直接提 PR 到 `main`

## 分支命名示例

- `feature/market-close-summary`
- `fix/checkpoint-date-guard`
- `docs/collaboration-readme`
- `refactor/sell-pipeline-split`

命名原则：

- 使用英文短语 + 短横线
- 名称直接说明改动主题
- 避免 `test1`、`update`、`temp` 这类无语义分支名

## 提交信息建议

优先沿用当前仓库已经在使用的前缀：

- `feat:`
- `fix:`
- `docs:`
- `refactor:`
- `test:`
- `chore:`

示例：

- `feat: add recent turnover fallback`
- `fix: avoid overlap between backfill windows`
- `docs: add collaborator onboarding guide`

## PR 要求

每个 PR 至少要满足下面几条：

- 目标单一，不混合多个不相关主题
- 说明“为什么改”和“改了什么”
- 写清影响范围：自动交易、市场分析、共享基础设施，还是仅文档
- 写清验证方式；如果没跑某项测试，也要写原因
- 如果改了命令、配置、流程或文档口径，必须同步更新文档
- 如果影响 MySQL、GM API、飞书 webhook 或真实交易语义，必须显式说明

## 测试要求

- 文档类改动：
  - 至少手动检查链接、命令、路径和分支名称是否正确
- Python 逻辑改动：
  - 至少运行与改动直接相关的单元测试
- 真实环境相关改动：
  - 在 PR 里写清你实际跑了哪些命令、依赖哪些外部系统、结果是什么
- `tests/debug/`：
  - 只在显式调试或排障时运行
  - 不把它当成默认 `pytest` 主链的一部分

## 文档同步规则

出现以下情况时，默认要同步更新文档：

- 改了命令
- 改了配置结构
- 改了运行前提
- 改了协作流程
- 改了对外行为，但现有文档已经写过这个行为

## 禁止事项

- 不直接 push 日常改动到 `main`
- 不直接 push 日常改动到 `dev`
- 不提交 `config/sim_account.yaml`
- 不提交真实 `gm.token`、MySQL 密码、飞书 webhook
- 不在一个 PR 里混入多个不相关改动
- 不在没有说明验证方式的情况下发起 PR
```

- [ ] **Step 2: 检查分支模型、命名规范和合并策略是否写全**

Run: `rg -n "main|dev|feature/market-close-summary|fix/checkpoint-date-guard|docs/collaboration-readme|Squash and merge|不直接 push" CONTRIBUTING.md`

Expected: 输出能看到 `main` / `dev` 职责、至少 3 个分支命名示例、`Squash and merge` 和禁止直推规则。

- [ ] **Step 3: 检查开发流程命令、测试义务和密钥约束是否明确**

Run: `rg -n "git fetch origin|git checkout dev|git pull origin dev|git checkout -b feature/market-close-summary|git push -u origin feature/market-close-summary|tests/debug|config/sim_account.yaml|飞书 webhook" CONTRIBUTING.md`

Expected: 输出能看到完整分支流程命令、`tests/debug/` 语义、私有配置限制和飞书密钥约束。

- [ ] **Step 4: 复查 README 与 CONTRIBUTING 的基础跳转是否成立**

Run: `Get-ChildItem README.md, CONTRIBUTING.md, docs\\auto-sell-runtime.md, docs\\market-analysis-runtime.md, config\\sim_account.example.yaml`

Expected: PowerShell 正常列出这 5 个文件且无 path-not-found 错误，说明 README 中引用的现有文件和新建的协作规范文件都已存在。

- [ ] **Step 5: 提交 CONTRIBUTING**

```bash
git add CONTRIBUTING.md
git commit -m "docs: add contribution workflow guide"
```

### Task 3: 新增 PR 模板并做最终一致性校验

**Files:**
- Create: `.github/pull_request_template.md`

- [ ] **Step 1: 写入 `.github/pull_request_template.md`**

```markdown
## 本次改动解决什么问题

- 说明这次改动对应的业务背景、缺陷现象，或协作痛点

## 主要改动点

- 列出 1 到 3 个最重要的改动点，避免把 diff 原样贴进来

## 影响范围

- [ ] 自动交易链路（`main.py trade`）
- [ ] 决策观测 / 调试工具
- [ ] 市场分析与飞书链路（`main.py scheduler`）
- [ ] 配置 / 基础设施 / 共享服务
- [ ] 仅文档 / 协作流程

## 验证方式

- 已运行：
  - `填写本次实际运行的命令，例如 conda run -n stock_analysis pytest tests/unit/test_config.py -q`
- 未运行项及原因：
  - `如无可写：无；如有跳过项，明确写原因`

## 配置 / 数据 / 外部依赖影响

- [ ] 无
- [ ] 有，说明如下：
  - `config/sim_account.yaml` 结构或示例配置是否受影响
  - MySQL schema / checkpoint / 回补逻辑是否受影响
  - 掘金终端 / GM API / 飞书 webhook / MySQL 连接是否受影响

## 文档更新

- [ ] 不需要
- [ ] 已更新，涉及：
  - `README.md`
  - `CONTRIBUTING.md`
  - `相关 docs 文件，例如 docs/market-analysis-runtime.md`

## 风险点与回滚方式

- 风险：写明最可能受影响的链路、配置或外部依赖；如果没有，写 `无新增高风险路径`
- 回滚：写明回滚 commit、回退配置、停止任务或恢复旧流程的方法
```

- [ ] **Step 2: 检查 PR 模板是否覆盖必填信息**

Run: `rg -n "本次改动解决什么问题|主要改动点|影响范围|验证方式|配置 / 数据 / 外部依赖影响|文档更新|风险点与回滚方式" .github/pull_request_template.md`

Expected: 输出包含以上 7 个章节，说明模板已经覆盖问题、改动、验证、外部影响和回滚信息。

- [ ] **Step 3: 跨文档检查环境名、配置路径和协作术语是否一致**

Run: `rg -n "stock_analysis|Squash and merge|config/sim_account.yaml|feature/market-close-summary|main.py scheduler" README.md CONTRIBUTING.md .github/pull_request_template.md`

Expected: README 与 CONTRIBUTING 都使用同一个 conda 环境名、相同的配置路径和相同的分支/合并术语；PR 模板至少包含配置影响说明，不出现第二套环境名或第二套分支口径。

- [ ] **Step 4: 做最终格式检查，避免留下空白差错或冲突改动**

Run: `git diff --check`

Expected: 无输出，说明新增文档没有多余空格、冲突标记或明显格式问题。

- [ ] **Step 5: 提交 PR 模板与最终一致性检查结果**

```bash
git add .github/pull_request_template.md README.md CONTRIBUTING.md
git commit -m "docs: add PR template for dev workflow"
```
