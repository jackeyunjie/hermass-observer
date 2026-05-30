#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from agently_adapter import a_share_actions


ROOT = Path(__file__).resolve().parents[1]
STEP_SPECS = [
    {
        "chunk": "预检",
        "state": "preflight",
        "runner": lambda params: a_share_actions.preflight(
            params["date"],
            params["previous_date"],
            timeout=params.get("command_timeout"),
        ),
    },
    {
        "chunk": "构建底座",
        "state": "build_foundation",
        "runner": lambda params: a_share_actions.build_foundation(
            params["date"],
            params["foundation_db"],
            timeout=params.get("command_timeout"),
        ),
        "after": lambda params, result: params.__setitem__("foundation_db", result["foundation_db"]),
    },
    {
        "chunk": "构建缓存",
        "state": "build_state_cache",
        "runner": lambda params: a_share_actions.build_state_cache(
            params["date"],
            params["foundation_db"],
            boundary_pct=params.get("boundary_pct", 0.03),
            timeout=params.get("command_timeout"),
        ),
    },
    {
        "chunk": "构建证据",
        "state": "build_strategy_evidence",
        "runner": lambda params: a_share_actions.build_strategy_evidence(
            params["date"],
            params["foundation_db"],
            lookback_days=params.get("lookback_days", 20),
            timeout=params.get("command_timeout"),
        ),
    },
    {
        "chunk": "构建信号账本",
        "state": "build_strategy_signal_ledger",
        "runner": lambda params: a_share_actions.build_strategy_signal_ledger(
            params["date"],
            params["foundation_db"],
            min_ef=params.get("min_ef", 2),
            timeout=params.get("command_timeout"),
        ),
    },
    {
        "chunk": "构建前向观察",
        "state": "build_forward_observation",
        "runner": lambda params: a_share_actions.build_forward_observation(
            params["date"],
            params["foundation_db"],
            windows=params.get("windows", "5,10,20"),
            timeout=params.get("command_timeout"),
        ),
    },
    {
        "chunk": "生成总报",
        "state": "build_daily_brief",
        "runner": lambda params: a_share_actions.build_daily_brief(
            params["date"],
            timeout=params.get("command_timeout"),
        ),
    },
    {
        "chunk": "校验核心产物",
        "state": "verify_core_outputs",
        "runner": lambda params: a_share_actions.verify_core_outputs(
            params["date"],
            foundation_db=params.get("foundation_db"),
            timeout=params.get("command_timeout"),
        ),
    },
]


def sanitize_import_path() -> None:
    root = ROOT.resolve()
    cleaned: list[str] = []
    for item in sys.path:
        if item == "":
            continue
        try:
            if Path(item).resolve() == root:
                continue
        except OSError:
            pass
        cleaned.append(item)
    sys.path[:] = cleaned


def _run_step(spec: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    result = spec["runner"](params)
    after = spec.get("after")
    if after:
        after(params, result)
    return result


def _register_step(flow, spec: dict[str, Any]) -> None:
    @flow.chunk(spec["chunk"])
    def _step(data):
        params = dict(data.input)
        result = _run_step(spec, params)
        data.set_state(spec["state"], result)
        return {**params, spec["state"]: result}


def build_flow():
    try:
        from agently import TriggerFlow
    except ModuleNotFoundError as exc:
        raise RuntimeError("Agently is not installed. Install an Agently 4.1.x release in the local venv first.") from exc

    flow = TriggerFlow(name="hermass-a-share-d1-core-flow")

    for spec in STEP_SPECS:
        _register_step(flow, spec)

    @flow.chunk("完成")
    def finish(data):
        result = {
            "ok": True,
            "scope": "a_share_only",
            "framework": "agently",
            "flow": "hermass-a-share-d1-core-flow",
            "date": data.input["date"],
            "previous_date": data.input["previous_date"],
            "foundation_db": data.input["foundation_db"],
            "steps": {spec["state"]: data.get_state(spec["state"]) for spec in STEP_SPECS},
            "research_only": True,
        }
        data.set_result(result)
        return result

    first = flow.to(STEP_SPECS[0]["chunk"])
    for spec in STEP_SPECS[1:]:
        first = first.to(spec["chunk"])
    first.to("完成")
    return flow


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the A-share-only Agently core flow.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--previous-date", required=True)
    parser.add_argument("--foundation-db", required=True)
    parser.add_argument("--boundary-pct", type=float, default=0.03)
    parser.add_argument("--lookback-days", type=int, default=20)
    parser.add_argument("--min-ef", type=int, default=2)
    parser.add_argument("--windows", default="5,10,20")
    parser.add_argument("--timeout", type=float, default=1800.0)
    parser.add_argument("--auto-close-timeout", type=float, default=1.0)
    args = parser.parse_args()

    sanitize_import_path()
    os.environ.setdefault("HERMASS_LLM_MODEL", "deepseekV4")
    payload: dict[str, Any] = {
        "date": args.date,
        "previous_date": args.previous_date,
        "foundation_db": args.foundation_db,
        "boundary_pct": args.boundary_pct,
        "lookback_days": args.lookback_days,
        "min_ef": args.min_ef,
        "windows": args.windows,
        "command_timeout": args.timeout,
    }
    flow = build_flow()
    execution = flow.create_execution(auto_close=True, auto_close_timeout=args.auto_close_timeout)
    result = execution.start(payload, timeout=None)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
