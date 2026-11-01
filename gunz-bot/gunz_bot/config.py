from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "default.json"


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).expanduser().open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: str | Path, data: dict[str, Any]) -> None:
    out = Path(path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")


def load_config(config_path: str | Path | None = None, profile_path: str | Path | None = None) -> dict[str, Any]:
    config = load_json(config_path or DEFAULT_CONFIG)
    if profile_path:
        profile = load_json(profile_path)
        config = deep_merge(config, profile)
    return config
