from __future__ import annotations

import sys
import time

from .actions import Action
from .backends import InputBackend


def release_keys(config: dict) -> list[str]:
    return list(config.get("keys", {}).values())


def release_mouse_buttons(config: dict) -> list[int]:
    buttons = [1, 2, 3]
    buttons.extend(int(button) for button in config.get("mouse", {}).values())
    return buttons


def countdown(seconds: float) -> None:
    whole_seconds = int(max(0, seconds))
    for remaining in range(whole_seconds, 0, -1):
        print(f"Starting in {remaining}...")
        time.sleep(1)
    fractional = max(0.0, seconds - whole_seconds)
    if fractional:
        time.sleep(fractional)


def execute_actions(
    actions: list[Action],
    backend: InputBackend,
    *,
    speed: float = 1.0,
    print_notes: bool = True,
) -> None:
    speed = max(0.05, speed)
    for action in actions:
        if action.kind == "note":
            if print_notes and action.label:
                print(f"[note] {action.label}")
            continue
        if action.kind == "wait":
            backend.sleep(action.seconds / speed)
            continue
        if action.kind == "key_down":
            backend.key_down(str(action.value))
            continue
        if action.kind == "key_up":
            backend.key_up(str(action.value))
            continue
        if action.kind == "tap_key":
            backend.key_down(str(action.value))
            backend.sleep(action.seconds / speed)
            backend.key_up(str(action.value))
            continue
        if action.kind == "mouse_down":
            backend.mouse_down(int(action.value))
            continue
        if action.kind == "mouse_up":
            backend.mouse_up(int(action.value))
            continue
        if action.kind == "click":
            backend.mouse_down(int(action.value))
            backend.sleep(action.seconds / speed)
            backend.mouse_up(int(action.value))
            continue
        if action.kind == "move_mouse":
            backend.move_mouse(action.dx, action.dy)
            continue
        raise ValueError(f"Unknown action kind: {action.kind}")


def safe_execute(
    actions: list[Action],
    backend: InputBackend,
    config: dict,
    *,
    speed: float = 1.0,
    print_notes: bool = True,
) -> None:
    try:
        execute_actions(actions, backend, speed=speed, print_notes=print_notes)
    except KeyboardInterrupt:
        print("\nInterrupted. Releasing held keys.", file=sys.stderr)
        raise
    finally:
        if config.get("safety", {}).get("release_keys_on_exit", True):
            backend.release_all(release_keys(config), release_mouse_buttons(config))
