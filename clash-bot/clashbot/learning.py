from __future__ import annotations

import json
import random
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_ROUTINE = "clash_attack_edrag_bottom_push_widescreen"


def timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value).strip("_") or "attack"


def default_learning_state() -> dict[str, Any]:
    return {
        "version": 1,
        "exploration_rate": 0.15,
        "min_samples_per_strategy": 2,
        "max_history": 200,
        "strategies": [
            {
                "name": "edrag_funnel",
                "routine": DEFAULT_ROUTINE,
                "base_score": 0,
                "notes": "Bottom-side E-Dragon push for the 1600x900 widescreen view: heroes make a lower funnel, Balloons scout traps, E-Dragons deploy as one line, then Rage/Freeze through core.",
            }
        ],
        "attacks": [],
    }


def load_learning_state(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return default_learning_state()
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{p} must contain a JSON object")
    data.setdefault("version", 1)
    data.setdefault("exploration_rate", 0.15)
    data.setdefault("min_samples_per_strategy", 2)
    data.setdefault("max_history", 200)
    data.setdefault("strategies", default_learning_state()["strategies"])
    data.setdefault("attacks", [])
    return data


def save_learning_state(path: str | Path, state: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def result_score(result: dict[str, Any] | None) -> float | None:
    if not result:
        return None
    has_score_input = any(result.get(key) is not None for key in ("stars", "destruction", "loot_gold", "loot_elixir", "loot_dark"))
    if not has_score_input:
        return None

    stars = float(result.get("stars") or 0)
    destruction = float(result.get("destruction") or 0)
    loot_gold = float(result.get("loot_gold") or 0)
    loot_elixir = float(result.get("loot_elixir") or 0)
    loot_dark = float(result.get("loot_dark") or 0)
    loot_score = min(50.0, (loot_gold + loot_elixir) / 20000.0 + loot_dark / 200.0)
    return stars * 100.0 + destruction + loot_score


def recompute_strategy_stats(state: dict[str, Any]) -> None:
    stats: dict[str, dict[str, Any]] = {}
    for strategy in state.get("strategies", []):
        if not isinstance(strategy, dict):
            continue
        name = str(strategy.get("name", strategy.get("routine", "strategy")))
        stats[name] = {
            "attempts": 0,
            "scored_attempts": 0,
            "score_total": 0.0,
            "best_score": None,
            "last_score": None,
        }

    for attack in state.get("attacks", []):
        if not isinstance(attack, dict):
            continue
        name = str(attack.get("strategy", ""))
        if name not in stats:
            stats[name] = {
                "attempts": 0,
                "scored_attempts": 0,
                "score_total": 0.0,
                "best_score": None,
                "last_score": None,
            }
        stats[name]["attempts"] += 1
        score = attack.get("score")
        if isinstance(score, (int, float)):
            stats[name]["scored_attempts"] += 1
            stats[name]["score_total"] += float(score)
            stats[name]["last_score"] = float(score)
            best = stats[name]["best_score"]
            stats[name]["best_score"] = float(score) if best is None else max(float(best), float(score))

    for strategy in state.get("strategies", []):
        if not isinstance(strategy, dict):
            continue
        name = str(strategy.get("name", strategy.get("routine", "strategy")))
        current = stats.get(name, {})
        scored = int(current.get("scored_attempts", 0))
        strategy["attempts"] = int(current.get("attempts", 0))
        strategy["scored_attempts"] = scored
        strategy["average_score"] = round(float(current.get("score_total", 0.0)) / scored, 2) if scored else None
        strategy["best_score"] = current.get("best_score")
        strategy["last_score"] = current.get("last_score")


def choose_strategy(state: dict[str, Any], forced: str | None = None) -> dict[str, Any]:
    strategies = [s for s in state.get("strategies", []) if isinstance(s, dict)]
    if not strategies:
        strategies = default_learning_state()["strategies"]
        state["strategies"] = strategies

    recompute_strategy_stats(state)

    if forced:
        for strategy in strategies:
            if forced in {str(strategy.get("name", "")), str(strategy.get("routine", ""))}:
                return strategy
        return {"name": safe_name(forced), "routine": forced, "base_score": 0}

    min_samples = int(state.get("min_samples_per_strategy", 2))
    under_tested = [s for s in strategies if int(s.get("attempts") or 0) < min_samples]
    if under_tested:
        return sorted(under_tested, key=lambda s: (int(s.get("attempts") or 0), str(s.get("name", ""))))[0]

    exploration_rate = float(state.get("exploration_rate", 0.15))
    if len(strategies) > 1 and random.random() < exploration_rate:
        return random.choice(strategies)

    return max(
        strategies,
        key=lambda s: (
            float(s.get("average_score") if s.get("average_score") is not None else s.get("base_score", 0)),
            -int(s.get("attempts") or 0),
            str(s.get("name", "")),
        ),
    )


def record_attack(
    state: dict[str, Any],
    *,
    strategy: dict[str, Any],
    profile: str,
    result: dict[str, Any] | None,
    screenshots: list[str],
    started_at: str,
    ended_at: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    score = result_score(result)
    attack = {
        "started_at": started_at,
        "ended_at": ended_at,
        "strategy": str(strategy.get("name", strategy.get("routine", "strategy"))),
        "routine": str(strategy.get("routine", "")),
        "profile": profile,
        "result": result or {},
        "score": round(score, 2) if score is not None else None,
        "screenshots": screenshots,
        "dry_run": dry_run,
    }

    attacks = state.setdefault("attacks", [])
    attacks.append(attack)
    max_history = int(state.get("max_history", 200))
    if max_history > 0 and len(attacks) > max_history:
        del attacks[:-max_history]
    recompute_strategy_stats(state)
    return attack


def strategy_summary(state: dict[str, Any]) -> list[dict[str, Any]]:
    recompute_strategy_stats(state)
    return [s for s in state.get("strategies", []) if isinstance(s, dict)]
