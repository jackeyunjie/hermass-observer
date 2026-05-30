#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def local_python() -> str:
    candidate = ROOT / ".venv" / "bin" / "python"
    return str(candidate) if candidate.exists() else sys.executable


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


def run_command(args: list[str], timeout: float | None = None) -> dict[str, Any]:
    cmd = [local_python(), "agently_adapter/stockpool_daily_runner.py", *args]
    print("+ " + " ".join(cmd), flush=True)
    completed = subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    if completed.stdout:
        print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n", flush=True)
    if completed.returncode != 0:
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(cmd)}")
    payload = parse_last_json(completed.stdout)
    return {
        "ok": True,
        "command": args[0] if args else "",
        "returncode": completed.returncode,
        "payload": payload,
    }


def parse_last_json(text: str) -> dict[str, Any] | list[Any] | None:
    stripped = text.strip()
    if not stripped:
        return None
    decoder = json.JSONDecoder()
    root_candidates = [match.start() for match in re.finditer(r"(?m)^[\[{]", stripped)]
    for index in reversed(root_candidates):
        try:
            value, end = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        if not stripped[index + end :].strip():
            return value
    return None


def build_flow():
    try:
        from agently import TriggerFlow
    except ModuleNotFoundError as exc:
        raise RuntimeError("Agently is not installed. Run `.venv/bin/python -m pip install agently==4.1.2.4`.") from exc

    flow = TriggerFlow(name="hermass-p116-full-compatibility-flow")

    @flow.chunk("运行兼容闭环")
    def run_full_compatibility_workflow(data):
        params = data.input
        args = [
            "run",
            "--date",
            params["date"],
            "--previous-date",
            params["previous_date"],
            "--foundation-db",
            params["foundation_db"],
        ]
        if params.get("download"):
            args.append("--download")
        if params.get("download_moneyflow"):
            args.append("--download-moneyflow")
        if params.get("build_raw"):
            args.append("--build-raw")
        if params.get("build_foundation"):
            args.append("--build-foundation")
        result = run_command(args, timeout=params.get("command_timeout"))
        data.set_state("full_workflow_run", result)
        return {**params, "full_workflow_run": result}

    @flow.chunk("校验公开产物")
    def verify_outputs(data):
        params = data.input
        verify_args = ["verify_public_outputs", "--date", params["date"]]
        foundation_db = params.get("foundation_db")
        if foundation_db:
            verify_args.extend(["--foundation-db", foundation_db])
        result = run_command(verify_args, timeout=params.get("command_timeout"))
        data.set_state("verification", result)
        return {**params, "verification": result}

    @flow.chunk("完成")
    def finish(data):
        result = {
            "ok": True,
            "framework": "agently",
            "scope": "a_share_only",
            "model": "deepseekV4",
            "flow": "hermass-p116-full-compatibility-flow",
            "flow_role": "full_workflow_compatibility_flow",
            "date": data.input["date"],
            "previous_date": data.input["previous_date"],
            "foundation_db": data.input["foundation_db"],
            "full_workflow_run": data.get_state("full_workflow_run"),
            "daily_run": data.get_state("full_workflow_run"),
            "verification": data.get_state("verification"),
            "research_only": True,
        }
        data.set_result(result)
        return result

    flow.to("运行兼容闭环").to("校验公开产物").to("完成")
    return flow


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the Hermass full workflow compatibility flow through Agently TriggerFlow."
    )
    parser.add_argument("--date", required=True)
    parser.add_argument("--previous-date", required=True)
    parser.add_argument("--foundation-db", required=True)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--download-moneyflow", action="store_true")
    parser.add_argument("--build-raw", action="store_true")
    parser.add_argument("--build-foundation", action="store_true")
    parser.add_argument("--timeout", type=float, default=1800.0, help="Timeout for each subprocess command.")
    parser.add_argument("--auto-close-timeout", type=float, default=1.0, help="Idle seconds before Agently closes the execution.")
    args = parser.parse_args()

    sanitize_import_path()
    os.environ.setdefault("HERMASS_LLM_MODEL", "deepseekV4")
    payload = {
        "date": args.date,
        "previous_date": args.previous_date,
        "foundation_db": args.foundation_db,
        "download": args.download,
        "download_moneyflow": args.download_moneyflow,
        "build_raw": args.build_raw,
        "build_foundation": args.build_foundation,
        "command_timeout": args.timeout,
    }
    flow = build_flow()
    execution = flow.create_execution(auto_close=True, auto_close_timeout=args.auto_close_timeout)
    result = execution.start(payload, timeout=None)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
