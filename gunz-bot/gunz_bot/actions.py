from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Action:
    kind: str
    value: str | int | None = None
    seconds: float = 0.0
    dx: int = 0
    dy: int = 0
    label: str = ""


def note(label: str) -> Action:
    return Action(kind="note", label=label)


def wait(seconds: float) -> Action:
    return Action(kind="wait", seconds=seconds)


def key_down(key: str) -> Action:
    return Action(kind="key_down", value=key)


def key_up(key: str) -> Action:
    return Action(kind="key_up", value=key)


def tap_key(key: str, seconds: float) -> Action:
    return Action(kind="tap_key", value=key, seconds=seconds)


def mouse_down(button: int) -> Action:
    return Action(kind="mouse_down", value=button)


def mouse_up(button: int) -> Action:
    return Action(kind="mouse_up", value=button)


def click(button: int, seconds: float) -> Action:
    return Action(kind="click", value=button, seconds=seconds)


def move_mouse(dx: int, dy: int) -> Action:
    return Action(kind="move_mouse", dx=dx, dy=dy)
