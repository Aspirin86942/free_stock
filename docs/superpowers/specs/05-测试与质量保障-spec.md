# 测试与质量保障 Spec

## 1. 文档目标

本文定义第一期实盘执行系统的测试范围、验证方式、质量门槛和交付证据。

测试与质量保障不是附属条目，而是第一期能否安全进入仿真运行的硬门槛。没有这一层约束，系统即使能启动，也无法证明不会误卖、重复卖或在错误状态下继续运行。

## 2. 本节定位

本节覆盖整个第一期系统，但重点服务以下目标：

- 保证关键判断可复现
- 保证关键状态流转可验证
- 保证接口异常不会静默穿透
- 保证仿真链路至少跑通过一次

本节不是第五层架构，但它对四层都施加约束。

## 3. 测试范围与非范围

### 3.1 测试范围

- 基础设施层的配置、调度、交易时段判断
- 数据接入层的对象转换、错误返回、委托和回报适配
- 核心决策层的止盈止损判断、卖出许可判断、逐标的状态流转
- 交易执行层的防重复卖单、委托提交、回报收口
- 仿真环境下的最小卖出闭环

### 3.2 非范围

- 回测收益验证
- 高频性能压测
- 多账户并发验证
- 第二期扩展能力验证

## 4. 与里程碑关系

| 里程碑 | 测试重点 |
| --- | --- |
| M0 | 启动、配置、账户连通、资金/持仓/行情可读 |
| M1 | 数据对象转换正确，委托和回报链路可用 |
| M2 | 多标的状态管理、止盈止损判断、防重复卖单 |
| M3 | 从触发到发单再到回报收口的完整闭环 |
| M4 | 日志完整、错误可审计、程序可稳定连续运行 |

## 5. 测试分层策略

### 5.1 单元测试

目标：验证纯逻辑和纯转换的正确性。

至少覆盖：

- 配置校验
- 交易时段判断
- 止盈判断
- 止损判断
- 卖出许可判断
- 同一标的防重复卖单
- 逐标的状态转换
- 掘金原始对象到内部对象的字段映射

### 5.2 集成测试

目标：验证模块之间的关键链路没有断点。

至少覆盖：

- 配置加载到运行上下文
- 持仓读取结果进入核心决策层
- 行情输入驱动卖出信号输出
- 卖出信号进入交易执行层
- 委托回报驱动状态从 `submitted` 进入 `filled`、`cancelled` 或 `failed`

### 5.3 仿真冒烟验证

目标：验证真实掘金仿真链路至少跑通一次。

至少验证：

- 能连接掘金仿真账户
- 能读取账户资金和全部持仓
- 有持仓但未触发时不会误下单
- 触发卖出时能成功发单
- 委托和成交回报能被接收并记录

### 5.4 运行期观察验证

目标：验证常驻程序在连续运行场景下没有出现明显失控。

至少关注：

- 日志是否按轮输出
- 接口失败是否落日志
- 非交易时段是否禁止发单
- 已有未完成卖单时是否被正确拦截

## 6. 关键测试对象

### 6.1 基础设施层

- 缺失必填配置时是否阻止启动
- 日志目录初始化失败时是否阻止启动
- 轮询间隔非法时是否阻止启动
- 交易时段判断是否正确区分 `pre_open`、`trading`、`post_close`、`closed_day`

### 6.2 数据接入层

- 账户快照字段是否完整
- 持仓快照字段是否完整
- 行情快照字段是否完整
- 委托提交结果是否包含明确状态
- 回报事件是否能正确映射为内部事件

### 6.3 核心决策层

- 当前价格达到止盈阈值时是否触发卖出
- 当前价格跌破止损阈值时是否触发卖出
- 可卖数量为零时是否禁止触发
- 非交易时段是否禁止进入执行层
- 同一标的已有未完成委托时是否禁止再次触发

### 6.4 交易执行层

- 接收到卖出信号后是否正确生成委托请求
- 委托提交失败时是否进入明确失败状态
- 部分成交后是否继续保持跟踪状态
- 已成交完成后是否禁止再次发单

## 7. 测试数据与环境约束

### 7.1 本地测试环境

- Python 3.10+
- 默认优先使用 `conda run -n test ...`
- 使用本地假数据或桩对象覆盖非必要的真实接口调用

### 7.2 仿真验证环境

- 使用东方财富掘金仿真账户
- 使用专用测试配置，不与未来实盘配置混用
- 冒烟测试前必须确认测试账户状态可控

### 7.3 数据要求

- 持仓测试数据必须覆盖”无持仓、单标的、多标的、可卖数量为零”四类情况
- 回报测试数据必须覆盖”已报、部成、已成、已撤、失败”五类状态
- 错误测试数据必须覆盖”鉴权失败、行情失败、委托失败、回报异常”四类情况

### 7.4 测试数据管理

#### 7.4.1 单元测试和集成测试

使用**测试桩（Test Stub）**模拟外部接口：

```python
# tests/fixtures/fake_gateways.py

from decimal import Decimal
from datetime import datetime
from zoneinfo import ZoneInfo

class FakeTradeGateway:
    “””模拟交易网关”””
    
    def __init__(self, scenario: str = “normal”):
        self.scenario = scenario
        self.submitted_orders = []
    
    def get_positions(self, account_id: str) -> list[PositionSnapshot]:
        if self.scenario == “no_position”:
            return []
        elif self.scenario == “single_position”:
            return [self._make_position(“SHSE.600036”, 100, Decimal(“10.00”))]
        elif self.scenario == “multiple_positions”:
            return [
                self._make_position(“SHSE.600036”, 100, Decimal(“10.00”)),
                self._make_position(“SHSE.600000”, 200, Decimal(“8.50”)),
            ]
        elif self.scenario == “zero_available”:
            return [self._make_position(“SHSE.600036”, 100, Decimal(“10.00”), available=0)]
        return []
    
    def _make_position(
        self,
        symbol: str,
        volume: int,
        cost_price: Decimal,
        available: int | None = None
    ) -> PositionSnapshot:
        return PositionSnapshot(
            symbol=symbol,
            exchange=symbol.split(“.”)[0],
            volume=volume,
            available_volume=available if available is not None else volume,
            cost_price=cost_price,
            last_update_time=datetime.now(tz=ZoneInfo(“Asia/Shanghai”))
        )
    
    def submit_order(self, symbol: str, volume: int) -> OrderSubmitResult:
        if self.scenario == “submit_fail”:
            return OrderSubmitResult(
                accepted=False,
                order_id=None,
                symbol=symbol,
                message=”模拟提交失败”
            )
        
        order_id = f”ORDER_{len(self.submitted_orders) + 1}”
        self.submitted_orders.append((symbol, volume, order_id))
        
        return OrderSubmitResult(
            accepted=True,
            order_id=order_id,
            symbol=symbol,
            message=”模拟提交成功”
        )


class FakeMarketGateway:
    “””模拟行情网关”””
    
    def __init__(self, price_map: dict[str, Decimal] | None = None):
        self.price_map = price_map or {}
    
    def get_quotes(self, symbols: list[str]) -> list[QuoteSnapshot]:
        results = []
        for symbol in symbols:
            price = self.price_map.get(symbol, Decimal(“10.00”))
            results.append(QuoteSnapshot(
                symbol=symbol,
                last_price=price,
                quote_time=datetime.now(tz=ZoneInfo(“Asia/Shanghai”)),
                source=”fake”
            ))
        return results
```

**使用示例：**

```python
# tests/unit/test_decision.py

def test_take_profit_triggered():
    “””测试止盈触发”””
    # 准备测试数据
    trade_gateway = FakeTradeGateway(scenario=”single_position”)
    market_gateway = FakeMarketGateway(price_map={
        “SHSE.600036”: Decimal(“10.52”)  # 成本 10.00，涨幅 5.2%
    })
    
    # 执行决策
    decision = make_decision(
        trade_gateway=trade_gateway,
        market_gateway=market_gateway,
        take_profit_ratio=Decimal(“0.05”)  # 5%
    )
    
    # 验证结果
    assert decision.triggered is True
    assert decision.trigger_type == “take_profit”
```

#### 7.4.2 仿真冒烟验证

使用**专用测试账户**：

- 账户标识：`test-account-m0`（从掘金申请的仿真账户）
- 初始资金：10 万元
- 测试持仓：手动建仓 2-3 只股票（如 SHSE.600036、SHSE.600000）
- 配置文件：`config/test_account.yaml`（不提交到 git）

**测试前准备：**

1. 确认测试账户状态正常
2. 确认测试持仓存在且可卖数量 > 0
3. 备份当前配置和日志目录

**测试执行：**

```powershell
# 设置测试账户环境变量
$env:GM_ACCOUNT_ID = “test-account-m0”
$env:GM_TOKEN = Read-Host “GM_TOKEN”

# 运行冒烟测试
conda run -n test python main.py --config config/test_account.yaml
```

**测试后清理：**

1. 检查是否有未完成订单（通过掘金 Web 界面或日志）
2. 归档测试日志到 `logs/archive/test-YYYY-MM-DD/`
3. 记录测试结果到 `docs/test-reports/`

#### 7.4.3 测试数据版本管理

测试桩代码提交到 git：

```
tests/
├── fixtures/
│   ├── __init__.py
│   ├── fake_gateways.py      # 提交
│   └── test_scenarios.py     # 提交
├── unit/
└── integration/
```

测试配置不提交到 git：

```
config/
├── sim_account.example.yaml  # 提交（示例）
├── sim_account.yaml          # 不提交（本地）
└── test_account.yaml         # 不提交（本地）
```

## 8. 质量门槛

第一期最低质量门槛如下：

- 无持仓不发单
- 非交易时段不发单
- 同一标的不重复发单
- 接口失败必须有日志
- 回报异常必须有日志
- 核心状态流转可通过测试复现
- 关键链路至少完成一次仿真冒烟

## 9. 交付证据

每个里程碑完成时，至少保留以下证据：

- 测试命令
- 测试结果摘要
- 冒烟日志文件或截图
- 失败样例及处理记录

若某项验证因外部环境无法执行，必须明确写出未执行原因，不得默认为“已通过”。

## 10. 推荐验证命令

第一期建议至少保留以下命令约定：

```powershell
conda run -n test pytest
conda run -n test pytest tests/unit
conda run -n test pytest tests/integration
python main.py --config config/sim_account.yaml
```

如果后续项目目录调整，命令可以变，但必须保留“单元测试、集成测试、仿真冒烟”三类入口。

## 11. 本节完成定义

测试与质量保障可视为完成，至少需要满足以下条件：

- 已定义统一测试分层口径
- 关键逻辑和关键链路具备明确测试清单
- 仿真冒烟有固定入口
- 质量门槛可被执行和复查
- 每个里程碑都知道要交什么验证证据
