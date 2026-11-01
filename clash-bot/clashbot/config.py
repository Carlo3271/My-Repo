from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_json(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{p} must contain a JSON object")
    return data


def screen_from_profile(profile: dict[str, Any]) -> tuple[int, int] | None:
    screen = profile.get("screen")
    if not isinstance(screen, dict):
        return None
    width = screen.get("width")
    height = screen.get("height")
    if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
        return width, height
    return None


def display_from_profile(profile: dict[str, Any]) -> int | str | None:
    display = profile.get("display")
    if isinstance(display, dict):
        display_id = display.get("id")
        if isinstance(display_id, (int, str)):
            return display_id
    display_id = profile.get("display_id")
    if isinstance(display_id, (int, str)):
        return display_id
    return None
