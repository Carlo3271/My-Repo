from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PlannedUpgrade:
    id: str
    name: str
    score: float
    reason: str
    cost: dict[str, int]
    time_hours: float
    routine: str | None = None


def _cost_fits(cost: dict[str, int], resources: dict[str, int]) -> bool:
    return all(resources.get(k, 0) >= v for k, v in cost.items())


def _deduct(cost: dict[str, int], resources: dict[str, int]) -> None:
    for key, value in cost.items():
        resources[key] = resources.get(key, 0) - value


def _flag(upgrade: dict[str, Any], *names: str) -> bool:
    return any(bool(upgrade.get(name)) for name in names)


def _is_finished(upgrade: dict[str, Any]) -> bool:
    return _flag(upgrade, "done", "complete", "completed", "maxed")


def _is_town_hall_upgrade(upgrade: dict[str, Any]) -> bool:
    if _flag(upgrade, "town_hall_upgrade", "is_town_hall"):
        return True
    category = str(upgrade.get("category", "")).lower().replace("-", "_").replace(" ", "_")
    if category in {"town_hall", "townhall", "th"}:
        return True
    upgrade_id = str(upgrade.get("id", "")).lower().replace("-", "_").replace(" ", "_")
    name = str(upgrade.get("name", "")).lower().replace("-", "_").replace(" ", "_")
    return upgrade_id.startswith(("town_hall", "townhall", "th_")) or name.startswith(("town_hall", "townhall"))


def _town_hall_last_enabled(state: dict[str, Any]) -> bool:
    policy = str(state.get("town_hall_policy", "last")).lower()
    return bool(state.get("town_hall_last", True)) and policy not in {"off", "false", "disabled", "anytime"}


def _all_non_town_hall_upgrades_finished(state: dict[str, Any]) -> bool:
    for raw in state.get("upgrades", []):
        if not isinstance(raw, dict):
            continue
        if _is_town_hall_upgrade(raw):
            continue
        if not _is_finished(raw):
            return False
    return True


def _requires_ok(upgrade: dict[str, Any], state: dict[str, Any]) -> bool:
    requires = upgrade.get("requires", {})
    if not isinstance(requires, dict):
        return True
    town_hall = requires.get("town_hall")
    if isinstance(town_hall, int) and int(state.get("town_hall", 0)) < town_hall:
        return False
    if requires.get("all_other_upgrades_maxed") and not _all_non_town_hall_upgrades_finished(state):
        return False
    return True


def score_upgrade(upgrade: dict[str, Any], state: dict[str, Any]) -> tuple[float, str]:
    weights = state.get("weights", {})
    focus = set(state.get("focus", []))
    category = str(upgrade.get("category", "general"))

    score = float(upgrade.get("priority", 0))
    score += float(weights.get(category, 0)) * 10

    if category in focus:
        score += 25

    tags = set(upgrade.get("tags", []))
    if tags & focus:
        score += 15

    time_hours = float(upgrade.get("time_hours", 1))
    if time_hours <= float(state.get("builder_window_hours", 12)):
        score += 8

    cost = upgrade.get("cost", {})
    resources = state.get("resources", {})
    if isinstance(cost, dict) and isinstance(resources, dict) and cost:
        pressure = max((float(v) / max(float(resources.get(k, 1)), 1.0)) for k, v in cost.items())
        if pressure > 0.8:
            score -= (pressure - 0.8) * 25

    reason = f"{category}, priority {upgrade.get('priority', 0)}"
    if category in focus:
        reason += ", focus match"
    return score, reason


def plan_upgrades(state: dict[str, Any], max_count: int | None = None) -> list[PlannedUpgrade]:
    builders = state.get("builders", {})
    free_builders = int(builders.get("free", 1)) if isinstance(builders, dict) else 1
    limit = max_count or int(state.get("max_upgrades", free_builders))
    limit = max(0, min(limit, free_builders))

    resources = dict(state.get("resources", {}))
    candidates: list[PlannedUpgrade] = []

    for raw in state.get("upgrades", []):
        if not isinstance(raw, dict):
            continue
        if _is_finished(raw):
            continue
        if (
            _town_hall_last_enabled(state)
            and _is_town_hall_upgrade(raw)
            and not _all_non_town_hall_upgrades_finished(state)
        ):
            continue
        cost = raw.get("cost", {})
        if not isinstance(cost, dict):
            cost = {}
        normalized_cost = {str(k): int(v) for k, v in cost.items()}
        if not _requires_ok(raw, state):
            continue
        if not _cost_fits(normalized_cost, resources):
            continue

        score, reason = score_upgrade(raw, state)
        candidates.append(
            PlannedUpgrade(
                id=str(raw.get("id", raw.get("name", "upgrade"))),
                name=str(raw.get("name", raw.get("id", "Upgrade"))),
                score=score,
                reason=reason,
                cost=normalized_cost,
                time_hours=float(raw.get("time_hours", 0)),
                routine=raw.get("routine"),
            )
        )

    candidates.sort(key=lambda u: u.score, reverse=True)

    plan: list[PlannedUpgrade] = []
    for candidate in candidates:
        if len(plan) >= limit:
            break
        if _cost_fits(candidate.cost, resources):
            plan.append(candidate)
            _deduct(candidate.cost, resources)
    return plan
