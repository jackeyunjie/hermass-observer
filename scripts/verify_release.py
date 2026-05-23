#!/usr/bin/env python3
"""Verify Hermass Observer Product release artifacts."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED = [
    ROOT / "fixtures/daily_observation_card.json",
    ROOT / "fixtures/p116d_omni_summary.json",
    ROOT / "reports/import_manifest.json",
    ROOT / "public/index.html",
]

FORBIDDEN = [
    "D1视角_MN1状态",
    "D1_view_MN1_state",
    "MN1混沌值_仅背景",
    "W1混沌值_仅背景",
    "盘前保守口径",
    "买入",
    "卖出",
    "加仓",
    "减仓",
    "止盈",
    "止损",
    "荐股",
    "收益承诺",
    "策略已验证赚钱",
]

ALLOWED_DATA_LEVELS = {
    "L2_OFFICIAL_SR_KEY_POSITION_STATE_OBSERVATION",
    "L2_OMNI_CYCLE_ALIGNMENT_SMOKE",
}


def fail(errors: list[str], msg: str) -> None:
    errors.append(msg)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    errors: list[str] = []
    for path in REQUIRED:
        if not path.exists():
            fail(errors, f"missing required artifact: {path.relative_to(ROOT)}")

    if not errors:
        daily = load_json(ROOT / "fixtures/daily_observation_card.json")
        omni = load_json(ROOT / "fixtures/p116d_omni_summary.json")
        manifest = load_json(ROOT / "reports/import_manifest.json")
        if not daily.get("as_of_date"):
            fail(errors, "daily fixture missing as_of_date")
        if daily.get("data_level_current") not in ALLOWED_DATA_LEVELS:
            fail(errors, f"unexpected daily data_level_current: {daily.get('data_level_current')}")
        if omni.get("data_level") != "L2_OMNI_CYCLE_ALIGNMENT_SMOKE":
            fail(errors, f"unexpected omni data_level: {omni.get('data_level')}")
        if daily.get("research_only_flag") is not True:
            fail(errors, "daily fixture research_only_flag is not true")
        if omni.get("research_only_flag") is not True:
            fail(errors, "omni summary research_only_flag is not true")
        if manifest.get("research_only_flag") is not True:
            fail(errors, "manifest research_only_flag is not true")

    for path in REQUIRED:
        if not path.exists() or path.suffix.lower() not in {".json", ".html"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for token in FORBIDDEN:
            if token in text:
                fail(errors, f"forbidden token {token!r} in {path.relative_to(ROOT)}")
        if "prior_high_60" in text and "not official" not in text.lower():
            fail(errors, f"prior_high_60 appears outside explicit boundary context in {path.relative_to(ROOT)}")

    if errors:
        print("FAIL: Hermass Observer Product release")
        for error in errors:
            print("-", error)
        return 1
    print("PASS: Hermass Observer Product release verified")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
