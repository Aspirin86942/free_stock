# 协作者上手 README 与 PR 协作规范设计

日期：2026-04-26

## 1. 背景

当前仓库已经具备较完整的运行说明、调试入口和架构约束，但这些信息主要分散在以下位置：

- 根目录 `AGENTS.md`
- `docs/auto-sell-runtime.md`
- `docs/market-analysis-runtime.md`
- `docs/superpowers/specs/` 与 `docs/superpowers/plans/`

这带来一个明确的协作问题：

1. 新协作者第一次进入仓库时，没有一个位于根目录、面向“快速上手”的统一入口文档
2. 当前远端分支只有 `main`，还没有成型的多人协作分支模型说明
3. 仓库中没有可执行的 PR 模板，导致后续协作时容易出现“PR 信息不足、验证方式缺失、风险说明缺失”的问题

用户已经明确本次目标是：

1. README 以“协作者上手文档”为主，而不是对外展示页
2. 分支模型采用 `main` / `dev` / `feature/*`
3. 日常开发从 `dev` 切 `feature/*`，通过 PR 回 `dev`
4. `dev` 稳定后再合入 `main`
5. PR 合并方式统一为 `Squash and merge`
6. PR 规范不仅写成文档，还要落成可执行模板

因此，本次设计要解决的不是“再补一份说明”，而是要补齐一个最小但完整的协作入口：

- 新协作者能快速上手
- 日常开发有清晰分支规则
- 每次 PR 都有统一信息结构

## 2. 目标与非目标

### 2.1 目标

本次设计完成后，应满足以下目标：

1. 在仓库根目录新增一份面向协作者的 `README.md`
2. 新增 `CONTRIBUTING.md`，集中承载开发与协作规范
3. 新增 `.github/pull_request_template.md`，把 PR 规范落成可执行模板
4. 明确 `main` / `dev` / `feature/*` 的职责边界
5. 明确 PR 进入 `dev` 与 `main` 的最低门槛
6. 在文档中补充本项目特有的风险提示，降低协作者误操作概率

### 2.2 非目标

本次设计不包含以下事项：

1. 不在本次设计中引入 CI、GitHub Actions 或自动化门禁
2. 不在本次设计中配置 GitHub Branch Protection 规则
3. 不重写现有运行文档，只在新文档中建立索引和协作入口
4. 不调整现有业务代码、命令语义或目录结构
5. 不在本次设计中定义发布版本号策略或 changelog 自动化流程

## 3. 方案对比与选择

### 方案 A：只新增一个 `README.md`

- 做法：把项目介绍、开发流程、PR 规范全部写入一个根目录 `README.md`
- 优点：
  - 文件最少
  - 第一次落地最快
- 缺点：
  - 首页会很快膨胀
  - 协作规范容易被埋在长文档里
  - 后续维护时，“上手说明”和“协作制度”会相互缠绕

### 方案 B：`README.md` + `CONTRIBUTING.md` + `.github/pull_request_template.md`（选中）

- 做法：
  - `README.md` 负责协作者第一次进入仓库时的快速上手
  - `CONTRIBUTING.md` 负责开发流程、分支模型、测试与提交流程
  - `.github/pull_request_template.md` 负责每次 PR 的固定填写结构
- 优点：
  - 文档边界清晰
  - 最常看的信息放在最靠近入口的位置
  - PR 规范能进入日常动作，不只停留在“看过但没执行”
- 成本：
  - 比单文件方案多维护两个文件
  - 需要控制内容边界，避免重复

### 方案 C：在方案 B 基础上再新增详细协作手册

- 做法：新增 `docs/collaboration-workflow.md` 等更重的流程文档
- 优点：
  - 信息最完整
  - 适合多人、多角色、长期维护的团队
- 缺点：
  - 对当前“两人协作、快速建立秩序”的阶段偏重
  - 容易出现“文档建了但不常看”的情况

### 结论

选择方案 B，原因如下：

1. 能同时覆盖“第一次上手”“日常开发”“每次提 PR”三个核心场景
2. 相比单文件方案更利于长期维护
3. 相比更重的协作手册方案，更符合当前仓库规模和协作人数

## 4. 设计结论

### 4.1 新增文件清单

本次实现应新增以下文件：

1. `README.md`
2. `CONTRIBUTING.md`
3. `.github/pull_request_template.md`

三者职责必须明确分离：

1. `README.md` 解决“如何快速看懂并跑起来”
2. `CONTRIBUTING.md` 解决“如何按统一流程协作开发”
3. `pull_request_template.md` 解决“每次 PR 必须交代哪些信息”

### 4.2 `README.md` 的内容边界

`README.md` 应面向“新协作者第一次进入仓库”的场景，建议包含以下栏目：

1. 项目简介
2. 两条主链路概览
3. 环境与依赖前提
4. 快速开始
5. 常用命令
6. 项目结构
7. 协作流程摘要
8. 文档索引
9. 注意事项

其中关键要求如下：

1. 只保留最常用、最能帮助上手的命令，不把全部调试命令一股脑复制进去
2. 协作流程只写摘要，并明确引导到 `CONTRIBUTING.md`
3. 必须明确本项目依赖掘金终端、本地 endpoint、MySQL、飞书 webhook 等真实外部系统
4. 必须说明 `config/sim_account.yaml` 是本地私有配置，不可提交

### 4.3 `CONTRIBUTING.md` 的内容边界

`CONTRIBUTING.md` 应面向“准备开始改代码的协作者”，建议包含以下栏目：

1. 分支模型
2. 标准开发流程
3. 分支命名规范
4. 提交与 PR 要求
5. 测试要求
6. 文档同步规则
7. 禁止事项

其中关键约束如下：

1. `main` 只接收稳定版本，不作为日常开发分支
2. `dev` 是日常集成分支
3. 所有开发任务从最新 `dev` 创建 `feature/*`、`fix/*`、`docs/*` 或 `refactor/*` 分支
4. 所有改动默认通过 PR 合回 `dev`
5. `dev` 稳定后，再由维护者发起 `dev -> main` 的 PR
6. 禁止直接向 `main` 或 `dev` 推送日常改动

### 4.4 分支命名规范

建议在 `CONTRIBUTING.md` 中固定以下命名口径：

1. 功能改动：`feature/<topic>`
2. 缺陷修复：`fix/<topic>`
3. 文档改动：`docs/<topic>`
4. 重构整理：`refactor/<topic>`

命名原则如下：

1. 使用短横线连接英文短语
2. 一次分支只承载单一目的
3. 不使用无语义名称，如 `test1`、`update`、`temp`

### 4.5 PR 进入 `dev` 的门槛

PR 进入 `dev` 前，至少满足以下条件：

1. PR 目标单一，不混合多个不相关主题
2. PR 描述写清“为什么改”和“改了什么”
3. 至少说明本次改动影响了哪条链路、哪些文件或哪些命令
4. 至少运行与改动直接相关的测试，或明确说明未运行原因
5. 若修改了命令、配置、运行流程或协作规则，必须同步更新文档

### 4.6 PR 进入 `main` 的门槛

`dev -> main` 的 PR 应比普通日常 PR 更严格，至少满足：

1. 对应改动已经在 `dev` 分支完成一次协作验证
2. 没有未解释的跳测
3. 文档、模板与当前代码口径一致
4. PR 说明中明确本轮合入影响的是自动交易链路、市场分析链路，或二者皆有

### 4.7 合并策略

合并策略统一为 `Squash and merge`，原因如下：

1. 能保持 `dev` 和 `main` 的提交历史更干净
2. 更适合多人在小步 feature 分支上高频提交
3. 有利于后续回溯“某个功能或修复是在哪次 PR 合入的”

### 4.8 `.github/pull_request_template.md` 的字段设计

PR 模板应保持简洁，但必须覆盖高价值信息。建议固定为以下字段：

1. 本次改动解决什么问题
2. 主要改动点
3. 影响范围
4. 验证方式
5. 配置、数据或外部依赖是否受影响
6. 是否更新文档
7. 风险点与回滚方式

这样设计的目的是：

1. 强制说明变更目的，避免“只看 diff 才知道在干什么”
2. 强制说明验证动作，避免“改完但没人知道怎么验”
3. 强制说明外部影响，避免真实环境项目出现配置或依赖变更而无人注意

### 4.9 文档之间的链接关系

为避免内容重复，文档之间必须建立清晰的跳转关系：

1. `README.md` 链接 `CONTRIBUTING.md`
2. `README.md` 链接现有运行说明文档
3. `CONTRIBUTING.md` 可简要引用 `README.md` 中的环境前提，不重复展开运行说明

这一设计的核心目的是：让协作者先进入入口文档，再按需要跳到更细的说明，而不是在多个长文档之间盲找信息。

## 5. 项目特有注意事项

### 5.1 conda 环境口径必须统一

当前本地偏好文档与项目文档对默认 conda 环境存在不同口径，但仓库对协作者暴露时必须统一为一个名字。

基于当前项目文档与命令现状，本次文档应统一使用：

- `stock_analysis`

原因是：

1. `AGENTS.md` 中的运行命令已经全部以 `stock_analysis` 为主
2. 新协作者的第一目标是“按仓库说明跑通”，而不是理解本地个性化偏好

### 5.2 真实外部依赖必须显式标记

本项目不是纯本地可运行的离线仓库，至少涉及：

1. 掘金终端与本地 `127.0.0.1:7001`
2. MySQL
3. 飞书 webhook

因此文档必须明确区分：

1. 哪些命令是安全预览或本地自检
2. 哪些命令会触达真实外部系统

### 5.3 私有配置和密钥保护

以下信息必须在文档中反复明确：

1. `config/sim_account.yaml` 不可提交
2. `gm.token`、MySQL 连接信息、飞书 webhook 不可出现在 PR、issue 或截图中

### 5.4 `tests/debug/` 的语义必须讲清楚

新协作者很容易把 `tests/debug/` 误解为普通回归测试的一部分，因此文档必须明确：

1. `tests/unit/` 是默认主链回归
2. `tests/integration/` 依赖真实掘金终端
3. `tests/debug/` 是显式运行的真实环境调试入口，不进入默认门禁

### 5.5 文档更新义务

本项目的命令、配置和真实环境依赖较多，因此文档如果不跟着更新，很快就会失效。应明确以下规则：

1. 改命令，更新文档
2. 改配置结构，更新文档
3. 改协作流程，更新文档
4. 改运行前提，更新文档

## 6. 测试与验证要求

本次实现以文档与模板为主，不涉及业务逻辑修改，但仍应验证以下事项：

1. `README.md` 与 `CONTRIBUTING.md` 中的命令、路径、分支名写法与仓库现状一致
2. 新增的 Markdown 文件链接可正常解析
3. PR 模板字段覆盖设计要求，没有遗漏高价值项
4. 文档之间没有明显重复、冲突或相互矛盾

## 7. 风险与边界条件

本次实现需重点避免以下问题：

1. `README.md` 写得过长，重新变成一个难以扫描的总手册
2. `README.md` 与 `CONTRIBUTING.md` 重复堆砌同一批规则
3. PR 模板字段过多，导致协作者为了“填表”而不是为了“说清楚”
4. 把本地个人习惯误写成仓库公共规则
5. 在没有自动化门禁的前提下，文档写得过严，实际无法执行

## 8. 伪代码草案

### 8.1 目标

说明新协作者如何通过新增文档理解项目、按分支模型开发，并通过统一 PR 模板回到 `dev` 分支。

### 8.2 输入

- `repo_state`: 当前仓库结构、已有运行文档、现有命令与分支现状
- `collaboration_rules`: 已确认的协作约束，包括 `main/dev/feature/*`、`Squash and merge`
- `doc_targets`: `README.md`、`CONTRIBUTING.md`、`.github/pull_request_template.md`

### 8.3 输出

- `readme_entry`: 面向协作者的仓库首页入口文档
- `contributing_rules`: 面向开发者的协作规范文档
- `pr_template`: 每次提 PR 自动出现的结构化模板

### 8.4 伪代码草案

```python
# [伪代码草案]
# 目标：把“怎么上手”“怎么协作”“每次 PR 交代什么”拆成三个清晰载体，减少多人协作混乱
# 输入：
# - repo_state: 仓库当前已有的运行说明、命令、目录和分支现状
# - collaboration_rules: 已确认的协作规则，例如 main/dev/feature、PR 回 dev、squash merge
# - doc_targets: 计划新增的文档与模板文件
# 输出：
# - readme_entry: 新协作者第一次进入仓库时能快速扫描的入口文档
# - contributing_rules: 开发前必须遵守的协作规则
# - pr_template: 每次创建 PR 时自动出现的固定字段

def build_collaboration_docs(repo_state, collaboration_rules, doc_targets):
    # 1. 先抽取“新协作者第一天就需要知道”的信息，避免 README 一上来堆太多细节
    readme_entry = compose_readme(
        project_summary=repo_state.project_summary,
        quick_start=repo_state.safe_start_commands,
        structure=repo_state.top_level_structure,
        doc_index=repo_state.runtime_docs,
        key_warnings=repo_state.external_dependencies,
    )

    # 2. 把协作制度收口到 CONTRIBUTING，避免首页既讲业务又讲流程，导致读者抓不到重点
    contributing_rules = compose_contributing(
        branch_model=collaboration_rules.branch_model,
        branch_names=collaboration_rules.branch_naming,
        pr_requirements=collaboration_rules.pr_requirements,
        test_requirements=collaboration_rules.test_requirements,
        forbidden_actions=collaboration_rules.forbidden_actions,
    )

    # 3. 用 PR 模板把口头规则变成默认动作，减少“这次忘了写影响范围或验证方式”的情况
    pr_template = compose_pr_template(
        problem_statement=True,
        change_summary=True,
        impact_scope=True,
        verification=True,
        external_dependency_changes=True,
        docs_updated=True,
        rollback_plan=True,
    )

    # 4. 建立文档跳转关系，让协作者总能从 README 找到更细规则，而不是在仓库里盲搜
    link_documents(readme_entry, contributing_rules, repo_state.runtime_docs)

    # 5. 发布前做一致性检查，避免命令、环境名、路径与现有仓库口径打架
    validate_docs(
        readme_entry=readme_entry,
        contributing_rules=contributing_rules,
        pr_template=pr_template,
        repo_state=repo_state,
    )

    return {
        "readme_entry": readme_entry,
        "contributing_rules": contributing_rules,
        "pr_template": pr_template,
    }
```
