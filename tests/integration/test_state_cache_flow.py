import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def find_latest_cache_file(pattern: str):
    candidates = sorted(
        ROOT.glob(f"outputs/state_cache/{pattern}"),
        reverse=True,
    )
    for c in candidates:
        if c.exists() and c.stat().st_size > 0:
            return c
    return None


@pytest.mark.integration
class TestStateCacheFlow:

    def test_state_ef_cache_exists(self):
        path = find_latest_cache_file("state_ef_*.json")
        if path is None:
            pytest.skip("没有可用的 state_ef 缓存文件")
        assert path.exists()

    def test_state_ef_cache_valid_json(self):
        path = find_latest_cache_file("state_ef_*.json")
        if path is None:
            pytest.skip("没有可用的 state_ef 缓存文件")

        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data, (list, dict))

        if isinstance(data, dict) and "data" in data:
            items = data["data"]
        elif isinstance(data, list):
            items = data
        else:
            items = []

        if items:
            first = items[0]
            assert "stock_code" in first

    def test_state_ef_cache_contains_hex(self):
        path = find_latest_cache_file("state_ef_*.json")
        if path is None:
            pytest.skip("没有可用的 state_ef 缓存文件")

        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "data" in data:
            items = data["data"]
        elif isinstance(data, list):
            items = data
        else:
            pytest.skip("缓存数据格式无法解析")

        if items:
            first = items[0]
            has_hex = any(
                k for k in first
                if "hex" in k.lower() or "state" in k.lower()
            )
            assert has_hex, f"缓存条目不包含 state_hex 字段: {list(first.keys())}"

    def test_state_cache_roundtrip(self):
        path = find_latest_cache_file("state_ef_*.json")
        if path is None:
            pytest.skip("没有可用的 state_ef 缓存文件")

        data = json.loads(path.read_text(encoding="utf-8"))
        serialized = json.dumps(data, ensure_ascii=False)
        roundtripped = json.loads(serialized)
        assert roundtripped == data

    def test_schema_version_present(self):
        path = find_latest_cache_file("state_ef_*.json")
        if path is None:
            pytest.skip("没有可用的 state_ef 缓存文件")

        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            assert any(
                k for k in data
                if "version" in k.lower() or "schema" in k.lower()
            ) or "data" in data, "缓存文件缺少版本标识或数据字段"
