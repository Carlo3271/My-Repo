from __future__ import annotations

import random
from collections.abc import Callable

from .actions import Action, click, move_mouse, note, tap_key, wait


TechniqueBuilder = Callable[[dict, str], list[Action]]

TECHNIQUE_DESCRIPTIONS = {
    "butterfly": "Sword movement loop: jump, air dash, slash, block.",
    "slash-shot": "Sword movement into gun swap and shot.",
    "reload-shot": "Alternates guns with reload cancels for shotgun pacing.",
    "half-step": "Dash slash into gun shot with a second movement beat.",
    "wall-cancel": "Jump and sword cancel practice for wall movement footage.",
    "spar": "Randomized movement and attack drill for a private-room dummy bot.",
}

DIRECTION_KEYS = {
    "forward": "forward",
    "back": "back",
    "left": "left",
    "right": "right",
}


def timing(config: dict, name: str) -> float:
    return float(config["timing"][name])


def key(config: dict, logical_name: str) -> str:
    return str(config["keys"][logical_name])


def mouse(config: dict, logical_name: str) -> int:
    return int(config["mouse"][logical_name])


def key_tap(config: dict, logical_name: str, duration_name: str = "tap") -> list[Action]:
    return [tap_key(key(config, logical_name), timing(config, duration_name))]


def dash(config: dict, direction: str) -> list[Action]:
    logical = DIRECTION_KEYS[direction]
    gap = timing(config, "dash_gap")
    return [
        *key_tap(config, logical, "dash_tap"),
        wait(gap),
        *key_tap(config, logical, "dash_tap"),
    ]


def attack_click(config: dict) -> list[Action]:
    return [click(mouse(config, "attack"), timing(config, "mouse_click"))]


def butterfly_cycle(config: dict, direction: str) -> list[Action]:
    return [
        *key_tap(config, "jump"),
        wait(timing(config, "jump_to_dash")),
        *dash(config, direction),
        wait(timing(config, "dash_to_slash")),
        *attack_click(config),
        wait(timing(config, "slash_to_block")),
        *key_tap(config, "block", "block_hold"),
        wait(timing(config, "cycle_recover")),
    ]


def slash_shot_cycle(config: dict, direction: str) -> list[Action]:
    return [
        *key_tap(config, "sword"),
        wait(timing(config, "weapon_switch")),
        *key_tap(config, "jump"),
        wait(timing(config, "jump_to_dash")),
        *dash(config, direction),
        wait(timing(config, "dash_to_slash")),
        *attack_click(config),
        wait(timing(config, "slash_to_gun")),
        *key_tap(config, "gun1"),
        wait(timing(config, "weapon_switch")),
        *attack_click(config),
        wait(timing(config, "shot_recover")),
        *key_tap(config, "sword"),
        wait(timing(config, "cycle_recover")),
    ]


def reload_shot_cycle(config: dict, direction: str) -> list[Action]:
    return [
        *key_tap(config, "gun1"),
        wait(timing(config, "weapon_switch")),
        *attack_click(config),
        wait(timing(config, "shot_recover")),
        *key_tap(config, "reload"),
        wait(timing(config, "reload_cancel")),
        *key_tap(config, "gun2"),
        wait(timing(config, "weapon_switch")),
        *attack_click(config),
        wait(timing(config, "shot_recover")),
        *key_tap(config, "reload"),
        wait(timing(config, "reload_cancel")),
        *key_tap(config, "gun1"),
        wait(timing(config, "cycle_recover")),
    ]


def half_step_cycle(config: dict, direction: str) -> list[Action]:
    second_direction = "right" if direction == "left" else "left"
    return [
        *key_tap(config, "sword"),
        wait(timing(config, "weapon_switch")),
        *key_tap(config, "jump"),
        wait(timing(config, "jump_to_dash")),
        *dash(config, direction),
        wait(timing(config, "dash_to_slash")),
        *attack_click(config),
        wait(timing(config, "slash_to_gun")),
        *key_tap(config, "gun1"),
        wait(timing(config, "weapon_switch")),
        *dash(config, second_direction),
        wait(timing(config, "half_step_to_shot")),
        *attack_click(config),
        wait(timing(config, "shot_recover")),
        *key_tap(config, "sword"),
        wait(timing(config, "cycle_recover")),
    ]


def wall_cancel_cycle(config: dict, direction: str) -> list[Action]:
    return [
        *key_tap(config, "sword"),
        wait(timing(config, "weapon_switch")),
        *key_tap(config, "jump"),
        wait(timing(config, "wall_jump_delay")),
        *dash(config, direction),
        wait(timing(config, "dash_to_slash")),
        *attack_click(config),
        wait(timing(config, "slash_to_block")),
        *key_tap(config, "block", "block_hold"),
        wait(timing(config, "cycle_recover")),
    ]


def spar_cycle(config: dict, direction: str) -> list[Action]:
    rng = random.Random()
    picked = rng.choice([butterfly_cycle, slash_shot_cycle, reload_shot_cycle, half_step_cycle])
    picked_direction = rng.choice(["left", "right", "forward", "back"])
    aim_jitter = int(config.get("spar", {}).get("aim_jitter_px", 40))
    actions = picked(config, picked_direction)
    if aim_jitter > 0 and rng.random() < 0.75:
        actions.insert(0, move_mouse(rng.randint(-aim_jitter, aim_jitter), rng.randint(-aim_jitter // 2, aim_jitter // 2)))
    return actions


BUILDERS: dict[str, TechniqueBuilder] = {
    "butterfly": butterfly_cycle,
    "slash-shot": slash_shot_cycle,
    "reload-shot": reload_shot_cycle,
    "half-step": half_step_cycle,
    "wall-cancel": wall_cancel_cycle,
    "spar": spar_cycle,
}


def normalize_direction(direction: str, cycle_index: int) -> str:
    if direction == "alternate":
        return "left" if cycle_index % 2 == 0 else "right"
    return direction


def build_technique(config: dict, name: str, cycles: int, direction: str) -> list[Action]:
    if name not in BUILDERS:
        choices = ", ".join(sorted(BUILDERS))
        raise ValueError(f"Unknown technique {name!r}. Choices: {choices}")

    actions: list[Action] = []
    builder = BUILDERS[name]
    for index in range(max(1, cycles)):
        actions.extend(builder(config, normalize_direction(direction, index)))
    return actions


def build_demo(config: dict, cycles: int, direction: str) -> list[Action]:
    demo_plan = [
        ("butterfly", "Butterfly timing pass"),
        ("slash-shot", "Slash-shot transition pass"),
        ("reload-shot", "Reload-shot cancel pass"),
        ("half-step", "Half-step movement pass"),
        ("spar", "Random sparring pass"),
    ]
    actions: list[Action] = []
    for technique, label in demo_plan:
        actions.append(note(label))
        actions.extend(build_technique(config, technique, cycles, direction))
        actions.append(wait(0.35))
    return actions


def estimate_seconds(actions: list[Action]) -> float:
    return sum(max(0.0, action.seconds) for action in actions)


def cycles_for_seconds(config: dict, name: str, seconds: float, direction: str) -> int:
    one_cycle = build_technique(config, name, 1, direction if direction != "alternate" else "left")
    cycle_time = max(estimate_seconds(one_cycle), 0.05)
    return max(1, int(seconds / cycle_time) + 1)
