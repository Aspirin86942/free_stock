# Auto Sell Runtime

## 正式入口

自动卖出执行入口（需要先启动掘金终端）：

```bash
conda run -n stock_analysis python main.py --config config/sim_account.yaml
```

可选参数：

```bash
# 单轮执行
conda run -n stock_analysis python main.py --config config/sim_account.yaml --once

# 连续 3 轮执行
conda run -n stock_analysis python main.py --config config/sim_account.yaml --max-rounds 3
```

## Debug 工具

决策观测入口（只输出观测结果，不触发自动卖出）：

```bash
# 单轮观测
conda run -n stock_analysis python observe_decisions.py --config config/sim_account.yaml --once

# 连续 3 轮观测
conda run -n stock_analysis python observe_decisions.py --config config/sim_account.yaml --max-rounds 3
```

调试连通性：

```bash
conda run -n stock_analysis python tools/debug/check_connectivity.py --config config/sim_account.yaml
```

调试手工交易：

```bash
conda run -n stock_analysis python tools/debug/manual_trade.py --config config/sim_account.yaml --side sell --symbol SHSE.600839 --volume 100 --price-type market --timeout-seconds 60
```
