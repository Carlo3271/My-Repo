from __future__ import annotations

import json
import math
import random
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .backends import InputBackend
from .combos import build_technique
from .config import PROJECT_ROOT, save_json
from .runner import countdown, safe_execute


TUNED_TIMINGS = [
    "tap",
    "dash_tap",
    "dash_gap",
    "jump_to_dash",
    "dash_to_slash",
    "slash_to_block",
    "slash_to_gun",
    "block_hold",
    "weapon_switch",
    "shot_recover",
    "reload_cancel",
    "half_step_to_shot",
    "cycle_recover",
]


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def mutate_timing(base: dict[str, float], sigma: float) -> dict[str, float]:
    mutated = deepcopy(base)
    for name in TUNED_TIMINGS:
        if name not in mutated:
            continue
        factor = math.exp(random.gauss(0.0, sigma))
        mutated[name] = round(min(0.35, max(0.012, float(mutated[name]) * factor)), 4)
    return mutated


def score_candidate(auto_score: float | None) -> float:
    if auto_score is not None:
        print(f"Auto score: {auto_score}")
        return auto_score

    while True:
        raw = input("Score this attempt 0-5, or q to stop: ").strip().lower()
        if raw in {"q", "quit", "exit"}:
            raise KeyboardInterrupt
        try:
            score = float(raw)
        except ValueError:
            print("Enter a number from 0 to 5.")
            continue
        if 0.0 <= score <= 5.0:
            return score
        print("Score must be from 0 to 5.")


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True))
        handle.write("\n")


def learn_technique(
    *,
    config: dict,
    backend: InputBackend,
    technique: str,
    trials: int,
    cycles: int,
    direction: str,
    speed: float,
    window_name: str,
    no_focus: bool,
    initial_countdown: float,
    trial_gap: float,
    auto_score: float | None,
) -> Path:
    best_timing = deepcopy(config["timing"])
    best_score = -1.0
    history: list[dict[str, Any]] = []
    run_log = PROJECT_ROOT / "runs" / f"learn_{technique}_{timestamp()}.jsonl"

    print(f"Learning {technique}. Trials: {trials}. Cycles per attempt: {cycles}.")
    if initial_countdown > 0:
        print("Switch to the game/private room now.")
        countdown(initial_countdown)

    for trial in range(1, trials + 1):
        sigma = max(0.03, 0.22 * (1.0 - (trial - 1) / max(1, trials)))
        candidate_timing = mutate_timing(best_timing, sigma)
        candidate_config = deepcopy(config)
        candidate_config["timing"] = candidate_timing

        print(f"\nTrial {trial}/{trials}")
        print(
            "timing: "
            f"jump_to_dash={candidate_timing.get('jump_to_dash')}, "
            f"dash_to_slash={candidate_timing.get('dash_to_slash')}, "
            f"slash_to_block={candidate_timing.get('slash_to_block')}, "
            f"cycle_recover={candidate_timing.get('cycle_recover')}"
        )

        if not no_focus:
            backend.focus_window(window_name)
        if trial_gap > 0:
            backend.sleep(trial_gap)

        actions = build_technique(candidate_config, technique, cycles, direction)
        safe_execute(actions, backend, candidate_config, speed=speed, print_notes=False)
        score = score_candidate(auto_score)

        row = {
            "trial": trial,
            "technique": technique,
            "score": score,
            "timing": candidate_timing,
            "created_at": timestamp(),
        }
        history.append(row)
        append_jsonl(run_log, row)

        if score >= best_score:
            best_score = score
            best_timing = candidate_timing
            print(f"New best score: {best_score}")

    profile_path = PROJECT_ROOT / "profiles" / f"{technique}.json"
    save_json(
        profile_path,
        {
            "profile_name": f"learned-{technique}",
            "technique": technique,
            "best_score": best_score,
            "updated_at": timestamp(),
            "timing": best_timing,
            "learning": {
                "trials": trials,
                "cycles": cycles,
                "direction": direction,
                "run_log": str(run_log),
                "recent_history": history[-10:],
            },
        },
    )
    return profile_path
