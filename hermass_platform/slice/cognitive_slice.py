from datetime import datetime, timezone

from .data_contract import compute_slice_checksum


def query_cognitive_slice(
    foundation_db: str,
    user_id: str,
    target_date: str,
    offset: int = 0,
    limit: int = 5000,
) -> dict:
    return {
        "slice_type": "cognitive",
        "slice_id": f"cognitive_{user_id}_{target_date.replace('-', '')}",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "contract_version": "1.0.0",
        "source": {
            "foundation_db": foundation_db,
            "cache_date": target_date.replace("-", ""),
        },
        "params": {
            "user_id": user_id,
            "date": target_date,
            "offset": offset,
            "limit": limit,
        },
        "data": [],
        "summary": {
            "row_count": 0,
            "ef_distribution": {"ef0": 0, "ef1": 0, "ef2": 0, "ef3": 0},
            "truncated": False,
            "_notice": "认知切片待 W10 认知画像数据就绪后实现。当前返回空数据。",
        },
        "integrity": {
            "checksum": compute_slice_checksum([]),
            "row_count": 0,
        },
    }
