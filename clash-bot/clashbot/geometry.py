from __future__ import annotations

from typing import Any


Point = tuple[int, int]


def _scale(value: int | float, max_value: int) -> int:
    if isinstance(value, float) and 0 <= value <= 1:
        return round(value * max_value)
    return round(value)


def resolve_point(target: Any, profile: dict[str, Any], screen: tuple[int, int]) -> Point:
    width, height = screen

    if isinstance(target, str):
        anchors = profile.get("anchors", {})
        if target not in anchors:
            raise KeyError(f"anchor {target!r} not found in profile")
        return resolve_point(anchors[target], profile, screen)

    if isinstance(target, (list, tuple)) and len(target) == 2:
        return _scale(target[0], width), _scale(target[1], height)

    if isinstance(target, dict):
        if "anchor" in target:
            return resolve_point(target["anchor"], profile, screen)
        if "x" in target and "y" in target:
            return _scale(target["x"], width), _scale(target["y"], height)

    raise ValueError(f"cannot resolve point from {target!r}")
