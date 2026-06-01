#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import math
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
PROJECT_DIR = ROOT / "data" / "project"

NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def col_to_idx(ref: str) -> int:
    letters = "".join(ch for ch in ref if ch.isalpha())
    value = 0
    for ch in letters:
        value = value * 26 + ord(ch) - 64
    return value - 1


def cell_value(cell: ET.Element, shared_strings: list[str]) -> object:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(t.text or "" for t in cell.findall(".//a:t", NS))

    raw = cell.find("a:v", NS)
    if raw is None:
        return None
    text = raw.text or ""

    if cell_type == "s":
        return shared_strings[int(text)]
    if cell_type == "b":
        return text == "1"
    try:
        number = float(text)
    except ValueError:
        return text
    return int(number) if number.is_integer() else number


def parse_xlsx(path: Path) -> dict[str, list[dict[str, object]]]:
    sheets: dict[str, list[dict[str, object]]] = {}
    with ZipFile(path) as zf:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for item in root.findall("a:si", NS):
                shared_strings.append("".join(t.text or "" for t in item.findall(".//a:t", NS)))

        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        relmap = {rel.attrib["Id"]: rel.attrib["Target"].lstrip("/") for rel in rels}

        for sheet in workbook.find("a:sheets", NS):
            name = sheet.attrib["name"]
            rel_id = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
            target = relmap[rel_id]
            root = ET.fromstring(zf.read(target))
            matrix: list[list[object]] = []
            for row in root.findall(".//a:sheetData/a:row", NS):
                values: list[object] = []
                for cell in row.findall("a:c", NS):
                    idx = col_to_idx(cell.attrib.get("r", "A1"))
                    while len(values) <= idx:
                        values.append(None)
                    values[idx] = cell_value(cell, shared_strings)
                matrix.append(values)
            if not matrix:
                continue
            headers = [str(value).strip() if value is not None else "" for value in matrix[0]]
            rows: list[dict[str, object]] = []
            for values in matrix[1:]:
                rows.append(
                    {
                        headers[i]: values[i] if i < len(values) else None
                        for i in range(len(headers))
                        if headers[i]
                    }
                )
            sheets[name] = rows
    return sheets


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def fnum(value: object) -> float:
    try:
        if value in (None, ""):
            return float("nan")
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def pct(value: float) -> str:
    if math.isnan(value):
        return "NA"
    return f"{value:.2f}%"


def analyze_top20() -> tuple[list[dict[str, object]], dict[str, object]]:
    trades = read_csv(PROJECT_DIR / "top20_trades.csv")
    sheets = parse_xlsx(PROJECT_DIR / "top20_kline_data.xlsx")
    rows: list[dict[str, object]] = []

    for trade in trades:
        sheet = sheets.get(f"{trade['排名']}_{trade['股票代码']}", [])
        buy_date = trade["买入日期"]
        idx = next((i for i, row in enumerate(sheet) if str(row.get("日期"))[:10] == buy_date), None)
        if idx is None:
            continue
        row = sheet[idx]
        prev = sheet[idx - 1] if idx > 0 else {}
        close = fnum(row.get("收盘"))
        open_ = fnum(row.get("开盘"))
        low = fnum(row.get("最低"))
        ma25 = fnum(row.get("MA25"))
        ma25_prev = fnum(prev.get("MA25"))
        vol5 = fnum(row.get("VOL5"))
        vol60 = fnum(row.get("VOL60"))
        ma_dist = (close - ma25) / ma25 * 100 if ma25 else float("nan")
        low_ma_dist = (low - ma25) / ma25 * 100 if ma25 else float("nan")
        body = abs(close - open_) / close * 100 if close else float("nan")
        ma_up = ma25 > ma25_prev if not math.isnan(ma25) and not math.isnan(ma25_prev) else False
        vol_confirm = vol5 > vol60 if not math.isnan(vol5) and not math.isnan(vol60) else False
        close_near = abs(ma_dist) <= 2 if not math.isnan(ma_dist) else False
        low_touch = low_ma_dist <= 2 if not math.isnan(low_ma_dist) else False
        stop_fall = (close >= open_) or (body <= 1.5) if not math.isnan(body) else False
        combo = "|".join(
            [
                "MA25_UP" if ma_up else "MA25_NOT_UP",
                "VOL5_GT_VOL60" if vol_confirm else "VOL5_LE_VOL60",
                "CLOSE_NEAR_MA25" if close_near else "CLOSE_NOT_NEAR_MA25",
                "LOW_TOUCH_MA25" if low_touch else "LOW_NOT_TOUCH_MA25",
                "STOP_FALL" if stop_fall else "NO_STOP_FALL",
                trade["交易类型"],
            ]
        )
        rows.append(
            {
                "rank": int(trade["排名"]),
                "code": trade["股票代码"],
                "name": trade["股票名称"],
                "buy_date": buy_date,
                "return_pct": fnum(trade["收益率(%)"]),
                "trade_type": trade["交易类型"],
                "ma_angle": fnum(trade["买入时MA25角度"]),
                "strong_score": int(float(trade["强势评分"])),
                "confirm_score": int(float(trade["确认评分"])),
                "ma_up": ma_up,
                "vol5_gt_vol60": vol_confirm,
                "close_near_ma25": close_near,
                "low_touch_ma25": low_touch,
                "stop_fall": stop_fall,
                "ma_dist_pct": ma_dist,
                "low_ma_dist_pct": low_ma_dist,
                "body_pct": body,
                "combo": combo,
            }
        )

    total = len(rows)
    summary = {
        "total": total,
        "ma_up": sum(1 for row in rows if row["ma_up"]),
        "vol5_gt_vol60": sum(1 for row in rows if row["vol5_gt_vol60"]),
        "close_near_ma25": sum(1 for row in rows if row["close_near_ma25"]),
        "low_touch_ma25": sum(1 for row in rows if row["low_touch_ma25"]),
        "stop_fall": sum(1 for row in rows if row["stop_fall"]),
        "strong_ge_6": sum(1 for row in rows if row["strong_score"] >= 6),
        "confirm_le_2": sum(1 for row in rows if row["confirm_score"] <= 2),
        "combo_counts": Counter(row["combo"] for row in rows),
        "trade_type_counts": Counter(row["trade_type"] for row in rows),
    }
    return rows, summary


def analyze_recommendation(date_ymd: str) -> dict[str, object]:
    rows = read_csv(ROOT / "recommendation" / "outputs" / f"p116_recommendation_{date_ymd}.csv")
    strong = [row for row in rows if row.get("latest_2560_signal") == "ma2560_strong_hold"]
    state_counts = Counter(row.get("state", "") for row in strong)
    macro_counts = Counter(row.get("macro_etf_state", "") for row in strong)
    macro_ef_ge_2 = sum(1 for row in strong if fnum(row.get("macro_etf_ef_count")) >= 2)
    market_rows = read_csv(ROOT / "outputs" / "market_assets_state" / f"market_assets_state_{date_ymd}.csv")
    broad = [row for row in market_rows if row.get("asset_type") == "broad_index"]
    industry = [row for row in market_rows if row.get("asset_type") == "industry_etf"]
    return {
        "total_recommendations": len(rows),
        "strong_2560": len(strong),
        "strong_state_counts": state_counts,
        "strong_macro_counts": macro_counts,
        "strong_macro_ef_ge_2": macro_ef_ge_2,
        "strong_macro_missing": sum(1 for row in strong if not row.get("macro_etf_state")),
        "broad_index_counts": Counter(
            f"{row.get('mn1_state_hex')}/{row.get('w1_state_hex')}/{row.get('d1_state_hex')}" for row in broad
        ),
        "industry_ef_ge_2": sum(1 for row in industry if fnum(row.get("ef_count")) >= 2),
        "industry_total": len(industry),
    }


def write_report(
    path: Path,
    top_rows: list[dict[str, object]],
    top_summary: dict[str, object],
    rec: dict[str, object],
    date_ymd: str,
) -> None:
    total = int(top_summary["total"])
    lines = [
        "# 2560 state 与市场匹配复现检查",
        "",
        f"- 数据目录: `data/project`",
        f"- 推荐/市场状态日期: `{date_ymd}`",
        "",
        "## 结论",
        "",
        "2560 的“适合”组合可以复现，但需要分成两层理解：",
        "",
        "1. `data/project` 中的 2560 适合组合是均线/量能/回踩/止跌组合，不包含正式 P116 state 字段。",
        "2. 项目推荐输出中，`ma2560_strong_hold` 与 P116 个股 state 高度集中在 `E/E/F`、`E/F/F`、`E/F/E`；市场匹配由行业 ETF 的 E/F 周期数量提供支持。",
        "",
        "## data/project Top20 复算",
        "",
        f"- 样本数: {total}",
        f"- `VOL5 > VOL60`: {top_summary['vol5_gt_vol60']}/{total}",
        f"- 买入日低点触及 MA25 2% 区间: {top_summary['low_touch_ma25']}/{total}",
        f"- 买入日收盘在 MA25 2% 区间: {top_summary['close_near_ma25']}/{total}",
        f"- MA25 上行: {top_summary['ma_up']}/{total}",
        f"- 止跌代理成立: {top_summary['stop_fall']}/{total}",
        f"- 强势评分 >= 6: {top_summary['strong_ge_6']}/{total}",
        f"- 确认评分 <= 2: {top_summary['confirm_le_2']}/{total}",
        "",
        "最高频组合:",
    ]
    for combo, count in top_summary["combo_counts"].most_common(5):
        lines.append(f"- {count}/{total}: `{combo}`")

    lines.extend(
        [
            "",
            "买入日明细:",
            "",
            "| 排名 | 代码 | 名称 | 买入日 | 收益 | 类型 | MA25距离 | 低点距MA25 | 组合 |",
            "|---:|---|---|---|---:|---|---:|---:|---|",
        ]
    )
    for row in top_rows:
        lines.append(
            f"| {row['rank']} | {row['code']} | {row['name']} | {row['buy_date']} | "
            f"{row['return_pct']:.2f}% | {row['trade_type']} | {pct(row['ma_dist_pct'])} | "
            f"{pct(row['low_ma_dist_pct'])} | `{row['combo']}` |"
        )

    lines.extend(
        [
            "",
            "## P116 state 与市场匹配",
            "",
            f"- 推荐样本数: {rec['total_recommendations']}",
            f"- `ma2560_strong_hold`: {rec['strong_2560']}/{rec['total_recommendations']}",
            f"- 其中行业/市场 ETF `ef_count >= 2`: {rec['strong_macro_ef_ge_2']}/{rec['strong_2560']}",
            f"- 行业 ETF 缺失匹配字段: {rec['strong_macro_missing']}/{rec['strong_2560']}",
            f"- 全部行业 ETF 中 `ef_count >= 2`: {rec['industry_ef_ge_2']}/{rec['industry_total']}",
            "",
            "`ma2560_strong_hold` 对应个股 state 分布:",
        ]
    )
    for state, count in rec["strong_state_counts"].most_common():
        lines.append(f"- `{state}`: {count}")
    lines.append("")
    lines.append("`ma2560_strong_hold` 对应行业/市场 state 分布:")
    for state, count in rec["strong_macro_counts"].most_common():
        label = state or "NA"
        lines.append(f"- `{label}`: {count}")

    lines.extend(
        [
            "",
            "## 可复现规则",
            "",
            "可复现的市场匹配判断可以写成：",
            "",
            "```text",
            "2560适合 = VOL5 > VOL60",
            "        AND 买入日低点触及 MA25 2% 区间",
            "        AND (收盘在 MA25 2% 区间 OR 强势评分 >= 6)",
            "        AND 止跌代理成立",
            "",
            "P116个股匹配 = latest_2560_signal == ma2560_strong_hold",
            "             AND state IN {E/E/F, E/F/F, E/F/E}",
            "",
            "市场匹配成立 = P116个股匹配",
            "           AND (macro_etf_ef_count >= 2 OR 无行业ETF字段时仅记为个股规则成立)",
            "```",
            "",
            "注意：`data/project` 的历史 Top20 文件本身没有 MN1/W1/D1 state 字段，所以不能仅凭该目录直接证明历史买入日的正式 P116 state；需要同时保存当日 P116 state 快照或使用现有推荐输出交叉验证。",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze reproducible 2560/state/market match evidence.")
    parser.add_argument("--date", default="20260521", help="Recommendation and market state yyyymmdd.")
    parser.add_argument(
        "--output",
        default=str(ROOT / "outputs" / "project" / "2560_state_market_match.md"),
        help="Markdown report output path.",
    )
    args = parser.parse_args()

    top_rows, top_summary = analyze_top20()
    rec = analyze_recommendation(args.date)
    output = Path(args.output)
    write_report(output, top_rows, top_summary, rec, args.date)
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
