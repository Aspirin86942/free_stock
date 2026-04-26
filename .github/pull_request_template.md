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
