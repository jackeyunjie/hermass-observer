import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "platform" / "tier_config.yaml"

_tier_config = None


def _load_config() -> dict:
    global _tier_config
    if _tier_config is None:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            _tier_config = yaml.safe_load(f)
    return _tier_config


def get_tier_definition(tier: str) -> dict:
    cfg = _load_config()
    return cfg.get("tiers", {}).get(tier, cfg["tiers"]["free"])


def get_tier_list() -> list[dict]:
    cfg = _load_config()
    return [
        {"tier": tid, "name": td["name"], "price": td["price"], "price_text": td.get("price_text", f"¥{td['price']}/月")}
        for tid, td in cfg["tiers"].items()
    ]


def get_feature_list(tier: str) -> list[str]:
    return get_tier_definition(tier).get("features", [])


def get_limits(tier: str) -> dict:
    return get_tier_definition(tier).get("limits", {})


def get_upgrade_prompt(tier: str) -> str:
    return get_tier_definition(tier).get("upgrade_prompt", "")


def is_feature_allowed(tier: str, feature: str) -> bool:
    limits = get_limits(tier)
    return limits.get(feature, False)


def get_additional_products() -> list[dict]:
    cfg = _load_config()
    return cfg.get("additional_products", [])


def get_beta_default_tier() -> str:
    cfg = _load_config()
    return cfg.get("beta_default_tier", "basic")
