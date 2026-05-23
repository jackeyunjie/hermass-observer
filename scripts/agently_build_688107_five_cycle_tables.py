#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import agently

import build_anlu_intraday_h4_h1_views as build_views
import generate_anlu_boundary_state_views as build_home
from hermass_five_cycle_agently_contract import 校验五周期结果, 计算视角状态审计, 通用周期, 通用行数, 通用规则


ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path("/Users/lv111101/Documents/hongrun-chaos-trading-system/.venv/bin/python")
样本品种 = "688107"
样本名称 = "安路科技"
样本输出 = {
    "五周期审计数据": build_home.OUT_JSON,
    "首页表格": build_home.OUT_HTML,
    "明细表格": build_views.OUT_HTML,
    "明细数据": build_views.OUT_JSON,
}


def 读取五分钟数据() -> list[dict[str, Any]]:
    if not build_views.RAW_OUT.exists():
        raise RuntimeError(f"缺少五分钟原始数据：{build_views.RAW_OUT}")
    rows = []
    with build_views.RAW_OUT.open(encoding="utf-8", newline="") as f:
        for row in build_views.csv.DictReader(f):
            rows.append(
                {
                    **row,
                    "timestamp": build_views.parse_dt(row["timestamp"]),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                    "amount": float(row["amount"]),
                }
            )
    if not rows:
        raise RuntimeError("五分钟原始数据为空")
    return rows


def 固定观察态规则(观察行: dict[str, Any], 被观察周期: str, 被观察序列: list[dict[str, Any]], 被观察序号: int) -> dict[str, Any]:
    return 计算视角状态审计(
        观察行,
        被观察周期,
        被观察序列,
        被观察序号,
        build_views.ea,
        build_views.pd,
        build_views.decode_state,
        build_views.clean_value,
    )


flow = agently.TriggerFlow(name="通用五周期状态审计规则_当前样本688107")


@flow.chunk("通用规则输入")
def 通用规则输入(data):
    return {
        "当前样本品种": 样本品种,
        "当前样本名称": 样本名称,
        "周期": 通用周期,
        "行数": 通用行数,
        "规则": 通用规则,
    }


@flow.chunk("生成明细数据和明细页面")
def 生成明细数据和明细页面(data):
    rows_5m = 读取五分钟数据()
    views = build_views.build_views(rows_5m)
    payload = {
        "schema_version": "agently_通用五周期状态审计规则_样本688107_v1",
        "symbol": build_views.SYMBOL,
        "name": build_views.NAME,
        "state_hex_contract": 通用规则,
        "views": {key: views[key] for key in 通用周期},
        "row_audit": views["row_audit"],
        "native_audit": views["native_audit"],
        "debug": views["debug"],
    }
    build_views.OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    build_views.OUT_HTML.write_text(build_views.render_html(payload), encoding="utf-8")
    return payload


@flow.chunk("生成首页")
def 生成首页(data):
    source = json.loads(build_views.OUT_JSON.read_text(encoding="utf-8"))
    payload = {
        **source,
        "schema_version": "agently_通用五周期状态审计首页_样本688107_v1",
        "row_limits": 通用行数,
        "homepage_source_fixture": str(build_views.OUT_JSON),
    }
    build_home.OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    build_home.OUT_HTML.write_text(build_home.render_html(payload), encoding="utf-8")
    return payload


@flow.chunk("校验")
def 校验(data):
    result = 校验五周期结果(data.value)
    return {**result, "输出": {key: str(path) for key, path in 样本输出.items()}}


@flow.chunk("完成")
def 完成(data):
    data.set_result(data.value)
    return data.value


flow.to("通用规则输入").to("生成明细数据和明细页面").to("生成首页").to("校验").to("完成")


def main() -> int:
    execution = flow.start_execution({"命令": "按通用五周期状态审计规则生成当前样本 688107"})
    result = execution.get_result(timeout=120)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
