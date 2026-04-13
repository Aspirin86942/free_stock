#!/usr/bin/env python
"""
真实 gm.api 连通性验证脚本

用法：
    # 主账户（有持仓）
    python scripts/verify_gm_api.py a9efa143-52fb-11f0-82fa-52560acd7da0

    # 测试账户（空仓）
    python scripts/verify_gm_api.py ed77ffcb-3343-11f1-a6f9-52560acd7da0

环境要求：
    - Python 3.10.19 (stock_analysis 环境)
    - gm==3.0.183
    - 需要设置环境变量 GM_TOKEN
"""

from __future__ import annotations

import json
import os
import sys

import gm.api as gm


def verify_account(account_id: str, token: str) -> dict:
    """验证账户连通性并返回资金和持仓数据"""
    print(f"正在验证账户: {account_id}")
    print(f"Token: {token[:10]}...")

    # 设置 token
    gm.set_token(token)

    # 可选：设置服务地址（默认即可）
    # gm.set_serv_addr('127.0.0.1:7001')

    # 查询资金
    print("\n查询资金...")
    cash = gm.get_cash(account_id=account_id)
    if not cash:
        print("❌ 资金查询失败：返回 None")
        return {"success": False, "error": "empty_cash"}

    print("✅ 资金查询成功")
    print(f"  账户ID: {cash.account_id}")
    print(f"  总资产: {cash.nav}")
    print(f"  可用资金: {cash.available}")
    print(f"  持仓市值: {cash.market_value}")

    # 查询持仓
    print("\n查询持仓...")
    positions = gm.get_position(account_id=account_id)
    if positions is None:
        positions = []

    print(f"✅ 持仓查询成功，共 {len(positions)} 条")
    for pos in positions:
        print(f"  {pos.symbol}: 持仓 {pos.volume}, 可用 {pos.available}, 成本 {pos.vwap}")

    # 转换为字典格式
    cash_dict = {
        "account_id": cash.account_id,
        "nav": float(cash.nav),
        "available": float(cash.available),
        "balance": float(cash.balance),
        "market_value": float(cash.market_value),
    }

    positions_list = [
        {
            "symbol": pos.symbol,
            "volume": pos.volume,
            "available": pos.available,
            "vwap": float(pos.vwap) if hasattr(pos, "vwap") else None,
        }
        for pos in positions
    ]

    return {
        "success": True,
        "account_id": account_id,
        "cash": cash_dict,
        "positions": positions_list,
    }


def main():
    if len(sys.argv) < 2:
        print("用法: python scripts/verify_gm_api.py <account_id>")
        print("\n可用账户:")
        print("  主账户: a9efa143-52fb-11f0-82fa-52560acd7da0")
        print("  测试账户: ed77ffcb-3343-11f1-a6f9-52560acd7da0")
        sys.exit(1)

    account_id = sys.argv[1]
    token = os.getenv("GM_TOKEN")

    if not token:
        print("❌ 错误: 未设置环境变量 GM_TOKEN")
        print("\n请先设置:")
        print("  export GM_TOKEN='your-token'  # Linux/Mac")
        print("  $env:GM_TOKEN='your-token'    # Windows PowerShell")
        sys.exit(1)

    try:
        result = verify_account(account_id, token)
        print("\n" + "=" * 60)
        print("验证结果:")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        print("=" * 60)

        if result["success"]:
            print("\n✅ 验证成功！gm.api 连通性正常")
            sys.exit(0)
        else:
            print("\n❌ 验证失败")
            sys.exit(1)

    except Exception as e:
        print(f"\n❌ 验证过程中出错: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
