# Contributing Guide

本文档定义“两人协作、`dev` 集成、`feature/*` 开发、`main` 稳定发布”的目标协作规则。

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

## 启用前提

以下流程适用于仓库已启用 `dev` 集成分支的情况；若当前仓库尚未创建 `dev`，请先由维护者创建并维护该分支，再按本文流程协作。

## 标准开发流程

1. 同步远端 `dev`（仅在 `dev` 分支已创建时执行）

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
  - 包含调试相关测试
  - 其中带 `real_env_debug` 标记的用例默认不会进入常规 `pytest` 回归；需要显式指定 `tests/debug` 路径时再运行

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
