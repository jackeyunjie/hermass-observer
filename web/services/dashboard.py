import json
from pathlib import Path
from typing import Dict, Any

ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = ROOT / "outputs" / "debate" / "debate_dashboard_data.json"

def get_dashboard_metrics() -> Dict[str, Any]:
    if not DATA_FILE.exists():
        return {
            "fresh_text": "—", "fresh_color": "--yellow", "fresh_sub": "无数据",
            "cron_icon": "❓", "cron_color": "--yellow", "cron_sub": "未获取到本地状态",
            "test_count": 0, "test_color": "--yellow",
            "main_lines": 0, "main_color": "--yellow",
        }
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {
            "fresh_text": "—", "fresh_color": "--red", "fresh_sub": "解析失败",
            "cron_icon": "❌", "cron_color": "--red", "cron_sub": "解析失败",
            "test_count": 0, "test_color": "--red",
            "main_lines": 0, "main_color": "--red",
        }
