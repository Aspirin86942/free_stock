"""历史换手率回填脚本。

用途：
1. 扫描 market_daily_bar 中 turnover_rate 为空的交易日；
2. 通过掘金 API 重新拉取指定区间日线并补齐换手率；
3. 以 upsert 方式回写数据库，支持重复执行（幂等）。
"""

from __future__ import annotations

import argparse
import concurrent.futures
import importlib.util
import sys
import time
from datetime import date
from pathlib import Path

import yaml


def _ensure_local_src_on_path() -> None:
    """当 editable 安装失效时，允许直接从仓库运行脚本。"""
    if importlib.util.find_spec("gmtrade_live") is not None:
        return

    repo_root = Path(__file__).resolve().parents[1]
    src_path = repo_root / "src"
    if src_path.exists():
        sys.path.insert(0, str(src_path))


def _parse_date(value: str) -> date:
    """把 YYYY-MM-DD 解析为 date。"""
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"无效日期格式: {value}") from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="历史换手率回填工具")
    parser.add_argument("--config", required=True, help="配置文件路径")
    parser.add_argument("--start-date", type=_parse_date, help="可选，回填起始交易日")
    parser.add_argument("--end-date", type=_parse_date, help="可选，回填结束交易日")
    parser.add_argument("--batch-size", type=int, default=50, help="股票分批大小，默认 50")
    parser.add_argument(
        "--max-trade-days",
        type=int,
        default=10000,
        help="扫描缺失交易日的上限，默认 10000（足够覆盖近三年）",
    )
    parser.add_argument("--dry-run", action="store_true", help="仅统计缺口，不执行回填")
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="并发 worker 数，默认 1。建议先用 2~3 验证稳定性。",
    )
    return parser


def _count_missing_rows(
    repository: "MySQLMarketRepository",
    start_date: date,
    end_date: date,
) -> int:
    """统计指定区间内 turnover_rate 为空的记录数。"""
    if repository._connection is None:  # noqa: SLF001 - 仅脚本内使用
        return 0

    sql = """
        SELECT SUM(CASE WHEN turnover_rate IS NULL THEN 1 ELSE 0 END) AS missing_rows
        FROM market_daily_bar
        WHERE trade_date BETWEEN %s AND %s
    """
    with repository._connection.cursor() as cursor:  # noqa: SLF001 - 仅脚本内使用
        cursor.execute(sql, (start_date, end_date))
        row = cursor.fetchone()
    if not row or row["missing_rows"] is None:
        return 0
    return int(row["missing_rows"])


def _run_worker_batches(
    *,
    worker_name: str,
    gm_token: str,
    gm_endpoint: str,
    mysql_config: "MySQLConfig",
    indexed_batches: list[tuple[int, list[str]]],
    repair_start_date: date,
    repair_end_date: date,
    missing_trade_date_set: set[date],
    total_batches: int,
) -> int:
    """执行单个 worker 的批次任务。"""
    from gmtrade_live.gateways.gm_history_market_gateway import GMHistoryMarketGateway
    from gmtrade_live.repositories.mysql_market_repository import MySQLMarketRepository

    gateway = GMHistoryMarketGateway()
    gateway.connect(gm_token, gm_endpoint)
    repository = MySQLMarketRepository(mysql_config)
    repository.connect()

    total_affected_rows = 0
    try:
        for batch_index, batch_symbols in indexed_batches:
            bars = gateway.fetch_daily_bars(
                symbols=batch_symbols,
                start_date=repair_start_date,
                end_date=repair_end_date,
            )
            bars_to_upsert = [
                bar for bar in bars if bar.trade_date in missing_trade_date_set
            ]
            if bars_to_upsert:
                affected_rows = repository.upsert_daily_bars(bars_to_upsert)
                total_affected_rows += affected_rows
            else:
                affected_rows = 0

            if (batch_index + 1) % 5 == 0 or batch_index + 1 == total_batches:
                print(
                    f"[{worker_name}] [{batch_index + 1}/{total_batches}] "
                    f"本批影响: {affected_rows}, "
                    f"worker累计: {total_affected_rows}"
                )
    finally:
        repository.close()
    return total_affected_rows


def main() -> int:
    _ensure_local_src_on_path()

    from gmtrade_live.config import MySQLConfig
    from gmtrade_live.gateways.gm_history_market_gateway import GMHistoryMarketGateway
    from gmtrade_live.repositories.mysql_market_repository import MySQLMarketRepository

    args = _build_parser().parse_args()
    if args.batch_size <= 0:
        print("参数错误: --batch-size 必须大于 0")
        return 1
    if args.workers <= 0:
        print("参数错误: --workers 必须大于 0")
        return 1

    raw_config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    gm_raw = raw_config.get("gm", {})
    mysql_raw = raw_config.get("mysql", {})
    gm_token = str(gm_raw.get("token") or "")
    gm_endpoint = str(gm_raw.get("endpoint") or "127.0.0.1:7001")
    mysql_config = MySQLConfig(
        host=str(mysql_raw.get("host") or ""),
        port=int(mysql_raw.get("port") or 3306),
        database=str(mysql_raw.get("database") or ""),
        user=str(mysql_raw.get("user") or ""),
        password=str(mysql_raw.get("password") or ""),
    )

    if not gm_token:
        print("配置错误: gm.token 为空")
        return 1

    gateway = GMHistoryMarketGateway()
    repository = MySQLMarketRepository(mysql_config)

    started_at = time.time()
    gateway.connect(gm_token, gm_endpoint)
    repository.connect()

    try:
        latest_trade_date = repository.get_latest_trade_date_in_daily_bar()
        if latest_trade_date is None:
            print("未检测到 market_daily_bar 数据，跳过回填。")
            return 0

        missing_trade_dates = repository.get_trade_dates_with_missing_turnover(
            end_date=args.end_date or latest_trade_date,
            limit=args.max_trade_days,
        )
        if args.start_date is not None:
            missing_trade_dates = [d for d in missing_trade_dates if d >= args.start_date]
        if args.end_date is not None:
            missing_trade_dates = [d for d in missing_trade_dates if d <= args.end_date]

        if not missing_trade_dates:
            print("目标区间内无换手率缺口，无需回填。")
            return 0

        repair_start_date = min(missing_trade_dates)
        repair_end_date = max(missing_trade_dates)
        missing_trade_date_set = set(missing_trade_dates)
        missing_rows_before = _count_missing_rows(repository, repair_start_date, repair_end_date)

        print(
            "回填范围: "
            f"{repair_start_date} ~ {repair_end_date}, "
            f"缺失交易日: {len(missing_trade_dates)}, "
            f"缺失记录: {missing_rows_before}"
        )

        if args.dry_run:
            return 0

        symbols = repository.get_all_symbols()
        if not symbols:
            print("证券主数据为空，无法执行回填。")
            return 1

        batches = [
            symbols[i : i + args.batch_size]
            for i in range(0, len(symbols), args.batch_size)
        ]
        total_batches = len(batches)

        if args.workers == 1:
            total_affected_rows = _run_worker_batches(
                worker_name="W1",
                gm_token=gm_token,
                gm_endpoint=gm_endpoint,
                mysql_config=mysql_config,
                indexed_batches=list(enumerate(batches)),
                repair_start_date=repair_start_date,
                repair_end_date=repair_end_date,
                missing_trade_date_set=missing_trade_date_set,
                total_batches=total_batches,
            )
        else:
            worker_count = min(args.workers, total_batches)
            worker_batches: list[list[tuple[int, list[str]]]] = [
                [] for _ in range(worker_count)
            ]
            for batch_index, batch_symbols in enumerate(batches):
                worker_batches[batch_index % worker_count].append((batch_index, batch_symbols))

            total_affected_rows = 0
            with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = [
                    executor.submit(
                        _run_worker_batches,
                        worker_name=f"W{worker_index + 1}",
                        gm_token=gm_token,
                        gm_endpoint=gm_endpoint,
                        mysql_config=mysql_config,
                        indexed_batches=worker_batches[worker_index],
                        repair_start_date=repair_start_date,
                        repair_end_date=repair_end_date,
                        missing_trade_date_set=missing_trade_date_set,
                        total_batches=total_batches,
                    )
                    for worker_index in range(worker_count)
                ]
                for future in concurrent.futures.as_completed(futures):
                    total_affected_rows += future.result()

        missing_rows_after = _count_missing_rows(repository, repair_start_date, repair_end_date)
        elapsed = time.time() - started_at
        print(
            "回填完成: "
            f"累计影响 {total_affected_rows} 行, "
            f"缺失记录 {missing_rows_before} -> {missing_rows_after}, "
            f"耗时 {elapsed:.1f}s"
        )
        return 0
    finally:
        repository.close()


if __name__ == "__main__":
    raise SystemExit(main())
