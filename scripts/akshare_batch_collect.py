#!/usr/bin/env python3
"""
AKShare 批量数据采集脚本
采集三类数据：
1. 估值指标 (stock_value_em) - PE/PB/PEG/市现率/市销率
2. 前十大股东 (stock_gdfx_holding_analyse_em)
3. 券商评级 (stock_rank_forecast_cninfo)
"""

import argparse
import json
import socket
import sys
import time
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

import pandas as pd

try:
    import akshare as ak
except ImportError:
    ak = None


PROJECT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_DIR / "data" / "akshare_fundamental"
STOCK_LIST_FILE = Path("/tmp/stock_list.csv")
DEFAULT_HOLDER_REPORT_DATE = "20241231"
RETRY_TIMES = 3
RETRY_DELAY = 2
TYPE_HOSTS = {
    "value": ["datacenter-web.eastmoney.com", "www.eastmoney.com"],
    "holder": ["datacenter-web.eastmoney.com", "www.eastmoney.com"],
    "forecast": ["webapi.cninfo.com.cn"],
}


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _normalize_stock_code(value: object) -> str:
    text = str(value).strip()
    if "." in text:
        text = text.split(".")[0]
    return text.zfill(6) if text.isdigit() else text


def _hosts_for_type(data_type: str) -> list[str]:
    if data_type == "all":
        ordered: list[str] = []
        for key in ("value", "holder", "forecast"):
            for host in TYPE_HOSTS[key]:
                if host not in ordered:
                    ordered.append(host)
        return ordered
    return TYPE_HOSTS.get(data_type, [])


def check_network_hosts(hosts: Iterable[str]) -> list[str]:
    failures: list[str] = []
    for host in hosts:
        try:
            socket.gethostbyname_ex(host)
        except Exception as e:
            failures.append(f"{host}: {e}")
    return failures


def resolve_foundation_db(foundation_db: str | None = None) -> Path:
    if foundation_db:
        path = Path(foundation_db)
        if not path.exists():
            raise FileNotFoundError(f"foundation DB 不存在: {path}")
        return path

    try:
        from hermass_platform.agents.base_agent import find_foundation_db

        path = find_foundation_db()
        if path:
            return path
    except Exception:
        pass

    try:
        from hermass_platform.slice.slice_engine import find_latest_foundation_db

        path = find_latest_foundation_db()
        if path:
            return path
    except Exception:
        pass

    candidates = sorted(
        (PROJECT_DIR / "outputs").glob("p116_foundation_*/p116_foundation.duckdb"),
        reverse=True,
    )
    for candidate in candidates:
        if candidate.exists() and candidate.stat().st_size > 0:
            return candidate

    raise FileNotFoundError("未找到可用的 foundation DB，请使用 --foundation-db 显式指定。")


def load_stock_list(foundation_db: str | None = None, refresh_cache: bool = False) -> list[str]:
    if refresh_cache and STOCK_LIST_FILE.exists():
        STOCK_LIST_FILE.unlink()

    if STOCK_LIST_FILE.exists():
        df = pd.read_csv(STOCK_LIST_FILE)
        return [_normalize_stock_code(c) for c in df["stock_code"].tolist()]

    db_path = resolve_foundation_db(foundation_db)
    import duckdb

    conn = duckdb.connect(str(db_path))
    df = conn.execute("SELECT DISTINCT stock_code FROM daily_bars ORDER BY stock_code").fetchdf()
    conn.close()

    codes = [_normalize_stock_code(c) for c in df["stock_code"].tolist()]
    pd.DataFrame({"stock_code": codes}).to_csv(STOCK_LIST_FILE, index=False)
    return codes


def fetch_with_retry(func, *args, **kwargs):
    for attempt in range(RETRY_TIMES):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if attempt < RETRY_TIMES - 1:
                log(f"  重试 {attempt + 1}/{RETRY_TIMES}: {str(e)[:80]}")
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                raise
    return None


def collect_value_data(
    stock_codes: list[str],
    max_stocks: int | None = None,
) -> tuple[pd.DataFrame, str | None]:
    if max_stocks:
        stock_codes = stock_codes[:max_stocks]

    log(f"开始采集估值数据，共 {len(stock_codes)} 只股票...")
    all_data: list[pd.DataFrame] = []
    success = 0
    failed = 0

    for i, code in enumerate(stock_codes):
        if i % 100 == 0:
            log(f"  进度: {i}/{len(stock_codes)} (成功:{success} 失败:{failed})")

        try:
            df = fetch_with_retry(ak.stock_value_em, symbol=code)
            if df is not None and len(df) > 0:
                latest = df.iloc[0:1].copy()
                latest["stock_code"] = code
                all_data.append(latest)
                success += 1
            else:
                failed += 1
        except Exception as e:
            failed += 1
            if i % 500 == 0:
                log(f"  错误 {code}: {str(e)[:80]}")

        if i % 20 == 0 and i > 0:
            time.sleep(0.5)

    log(f"估值数据采集完成: 成功 {success}, 失败 {failed}")
    if not all_data:
        return pd.DataFrame(), "估值数据采集结果为空"
    return pd.concat(all_data, ignore_index=True), None


def collect_holder_data(
    stock_codes: list[str],
    report_date: str = DEFAULT_HOLDER_REPORT_DATE,
    max_stocks: int | None = None,
) -> tuple[pd.DataFrame, str | None]:
    if max_stocks:
        stock_codes = stock_codes[:max_stocks]

    log(f"开始采集前十大股东数据，报告期 {report_date}，目标股票 {len(stock_codes)} 只...")

    try:
        df = fetch_with_retry(ak.stock_gdfx_holding_analyse_em, date=report_date)
    except Exception as e:
        message = f"前十大股东采集失败: {e}"
        log(message)
        return pd.DataFrame(), message

    if df is None or len(df) == 0:
        message = "前十大股东: 无数据"
        log(message)
        return pd.DataFrame(), message

    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    df["股票代码"] = df["股票代码"].map(_normalize_stock_code)
    df = df[df["股票代码"].isin(set(stock_codes))].copy()

    if "序号" in df.columns:
        rank_series = pd.to_numeric(df["序号"], errors="coerce")
        df = df[rank_series <= 10].copy()

    df["stock_code"] = df["股票代码"]
    covered = df["股票代码"].nunique() if len(df) else 0
    log(f"前十大股东采集完成: {len(df)} 行，覆盖 {covered} 只股票")
    if len(df) == 0:
        return df, "股东全量接口返回成功，但目标股票过滤后为空"
    return df, None


def collect_forecast_data(date_str: str | None = None) -> tuple[pd.DataFrame, str | None]:
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")

    log(f"开始采集券商评级数据，日期: {date_str}...")

    try:
        df = fetch_with_retry(ak.stock_rank_forecast_cninfo, date=date_str)
        if df is not None and len(df) > 0:
            log(f"券商评级采集完成: {len(df)} 条记录")
            return df, None
        message = "券商评级: 无数据"
        log(message)
        return pd.DataFrame(), message
    except Exception as e:
        message = f"券商评级采集失败: {e}"
        log(message)
        return pd.DataFrame(), message


def save_data(df: pd.DataFrame, name: str, date_str: str):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    parquet_path = OUTPUT_DIR / f"{name}_{date_str}.parquet"
    df.to_parquet(parquet_path, index=False)
    log(f"  已保存 Parquet: {parquet_path} ({len(df)} 行)")

    csv_path = OUTPUT_DIR / f"{name}_{date_str}.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    log(f"  已保存 CSV: {csv_path}")

    return {"parquet": str(parquet_path), "csv": str(csv_path), "rows": len(df)}


def main():
    parser = argparse.ArgumentParser(description="AKShare 批量数据采集")
    parser.add_argument("--type", choices=["value", "holder", "forecast", "all"], default="all", help="采集类型")
    parser.add_argument("--max-stocks", type=int, default=None, help="最大采集股票数（测试用）")
    parser.add_argument("--date", type=str, default=None, help="兼容旧参数，等同于 --forecast-date")
    parser.add_argument("--forecast-date", type=str, default=None, help="券商评级日期 (YYYYMMDD)")
    parser.add_argument("--holder-report-date", type=str, default=DEFAULT_HOLDER_REPORT_DATE, help="股东报告期 (YYYYMMDD)")
    parser.add_argument("--foundation-db", type=str, default=None, help="显式指定 foundation DB")
    parser.add_argument("--refresh-stock-list", action="store_true", help="强制重建股票列表缓存")
    parser.add_argument("--skip-network-check", action="store_true", help="跳过 DNS/网络预检")
    args = parser.parse_args()

    if ak is None:
        log("错误: 未安装 akshare，请先安装: pip install akshare")
        sys.exit(1)

    if not args.skip_network_check:
        host_failures = check_network_hosts(_hosts_for_type(args.type))
        if host_failures:
            log("错误: Python 运行时无法解析以下数据源域名:")
            for item in host_failures:
                log(f"  - {item}")
            log("建议先排查 Python 运行时 DNS / 代理 / 网络沙箱，再重试。")
            sys.exit(3)

    forecast_date = args.forecast_date or args.date or datetime.now().strftime("%Y%m%d")
    foundation_db = resolve_foundation_db(args.foundation_db)
    stock_codes = load_stock_list(str(foundation_db), refresh_cache=args.refresh_stock_list)
    log(f"使用 foundation DB: {foundation_db}")
    log(f"加载股票列表: {len(stock_codes)} 只")

    results: dict[str, dict] = {}
    errors: dict[str, str] = {}
    requested_types: list[str] = []

    if args.type in ("value", "all"):
        requested_types.append("value")
        log("=" * 50)
        log("【1/3】采集估值指标 (PE/PB/PEG/市现率/市销率)")
        df, error = collect_value_data(stock_codes, max_stocks=args.max_stocks)
        if len(df) > 0:
            results["value"] = save_data(df, "stock_value", forecast_date)
        if error:
            errors["value"] = error

    if args.type in ("holder", "all"):
        requested_types.append("holder")
        log("=" * 50)
        log(f"【2/3】采集前十大股东 (报告期 {args.holder_report_date})")
        df, error = collect_holder_data(
            stock_codes,
            report_date=args.holder_report_date,
            max_stocks=args.max_stocks,
        )
        if len(df) > 0:
            results["holder"] = save_data(df, "stock_holder_top10", args.holder_report_date)
        if error:
            errors["holder"] = error

    if args.type in ("forecast", "all"):
        requested_types.append("forecast")
        log("=" * 50)
        log(f"【3/3】采集券商评级 ({forecast_date})")
        df, error = collect_forecast_data(forecast_date)
        if len(df) > 0:
            results["forecast"] = save_data(df, "stock_forecast", forecast_date)
        if error:
            errors["forecast"] = error

    log("=" * 50)
    log("采集完成汇总:")
    for key, info in results.items():
        log(f"  {key}: {info['rows']} 行 -> {info['parquet']}")

    meta = {
        "generated_at": datetime.now().isoformat(),
        "forecast_date": forecast_date,
        "holder_report_date": args.holder_report_date,
        "foundation_db": str(foundation_db),
        "total_stocks": len(stock_codes),
        "requested_types": requested_types,
        "results": results,
        "errors": errors,
    }
    meta_path = OUTPUT_DIR / f"meta_{forecast_date}.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    log(f"元数据已保存: {meta_path}")

    if errors:
        log("采集存在错误:")
        for key, message in errors.items():
            log(f"  {key}: {message}")
        sys.exit(2)


if __name__ == "__main__":
    main()
