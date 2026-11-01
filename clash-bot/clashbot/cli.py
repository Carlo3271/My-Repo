from __future__ import annotations

import argparse
import time
from pathlib import Path

from .adb import ADB
from .config import display_from_profile, load_json
from .config import screen_from_profile
from .learning import (
    choose_strategy,
    load_learning_state,
    recompute_strategy_stats,
    record_attack,
    result_score,
    safe_name,
    save_learning_state,
    strategy_summary,
    timestamp,
)
from .macro import MacroRunner
from .planner import plan_upgrades


def _coerce_display(value: object) -> int | str | None:
    if value is None or isinstance(value, int):
        return value
    if isinstance(value, str):
        if value.lower() == "auto":
            return "auto"
        return int(value)
    raise ValueError(f"invalid display value: {value!r}")


def _resolve_display(
    args: argparse.Namespace,
    profile: dict | None = None,
    *,
    allow_auto: bool = True,
) -> int | None:
    raw = _coerce_display(getattr(args, "display", None))
    if raw is None and profile is not None:
        raw = _coerce_display(display_from_profile(profile))

    if raw == "auto":
        if getattr(args, "dry_run", False):
            return None
        if not allow_auto:
            raise ValueError("--display auto is not available for this command")
        package = str((profile or {}).get("package", getattr(args, "package", "com.supercell.clashofclans")))
        screen = None
        if profile is not None:
            screen = profile.get("screen")
            if isinstance(screen, dict):
                width = screen.get("width")
                height = screen.get("height")
                if isinstance(width, int) and isinstance(height, int):
                    screen = (width, height)
                else:
                    screen = None
        probe = ADB(adb_path=args.adb, serial=args.serial, dry_run=False)
        display_id = probe.detect_display_id(package, size=screen)
        print(f"detected display {display_id} for {package}")
        return display_id

    return raw


def _adb_from_args(args: argparse.Namespace, display_id: int | None = None) -> ADB:
    if display_id is None:
        display_id = _resolve_display(args, allow_auto=False)
    return ADB(
        adb_path=args.adb,
        serial=args.serial,
        display_id=display_id,
        dry_run=getattr(args, "dry_run", False),
    )


def cmd_devices(args: argparse.Namespace) -> int:
    adb = _adb_from_args(args)
    for serial, status in adb.devices():
        print(f"{serial}\t{status}")
    return 0


def cmd_launch(args: argparse.Namespace) -> int:
    display_id = _resolve_display(args, allow_auto=False)
    adb = _adb_from_args(args, display_id)
    if display_id is not None and args.activity:
        adb.run(
            ["shell", "am", "start", "--display", str(display_id), "-n", f"{args.package}/{args.activity}"],
            stdout=None,
        )
    else:
        adb.launch(args.package, args.activity)
    return 0


def cmd_screenshot(args: argparse.Namespace) -> int:
    profile = load_json(args.profile) if args.profile else None
    display_id = _resolve_display(args, profile, allow_auto=profile is not None)
    adb = _adb_from_args(args, display_id)
    out = adb.screencap(args.out, display_id)
    print(out)
    return 0


def cmd_tap(args: argparse.Namespace) -> int:
    display_id = _resolve_display(args, allow_auto=False)
    adb = _adb_from_args(args, display_id)
    adb.tap(args.x, args.y)
    return 0


def cmd_zoom_out(args: argparse.Namespace) -> int:
    profile = load_json(args.profile)
    screen = screen_from_profile(profile)
    if screen is None:
        raise ValueError(f"profile {args.profile!r} must define screen width and height")
    display_id = _resolve_display(args, profile)
    adb = _adb_from_args(args, display_id)
    print(f"zooming out display {display_id if display_id is not None else 'default'} with {args.steps} pinch gesture(s)")
    adb.zoom_out(screen[0], screen[1], steps=args.steps, duration_ms=args.duration_ms)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    profile = load_json(args.profile)
    routine = load_json(args.routine)
    display_id = _resolve_display(args, profile)
    adb = _adb_from_args(args, display_id)
    runner = MacroRunner(
        adb,
        profile,
        base_dir=Path(args.routine).resolve().parent.parent,
        dry_run=args.dry_run,
    )
    for i in range(args.repeat):
        if args.repeat > 1:
            print(f"cycle {i + 1}/{args.repeat}")
        runner.run(routine)
        if i + 1 < args.repeat and args.delay > 0 and not args.dry_run:
            time.sleep(args.delay)
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    state = load_json(args.state)
    plan = plan_upgrades(state, args.max)
    if not plan:
        print("no affordable upgrades matched the current constraints")
        return 0

    for i, upgrade in enumerate(plan, start=1):
        cost = ", ".join(f"{k}={v}" for k, v in upgrade.cost.items()) or "free"
        routine = f", routine={upgrade.routine}" if upgrade.routine else ""
        print(
            f"{i}. {upgrade.name} "
            f"(score={upgrade.score:.1f}, time={upgrade.time_hours:g}h, cost={cost}{routine})"
        )
        print(f"   {upgrade.reason}")
    return 0


def _routine_path(routines_dir: str | Path, routine_name: str) -> Path:
    path = Path(routine_name)
    if path.suffix != ".json":
        path = path.with_suffix(".json")
    if not path.is_absolute() and len(path.parts) == 1:
        path = Path(routines_dir) / path
    return path


def _attack_result_from_args(args: argparse.Namespace) -> dict[str, int | float] | None:
    result: dict[str, int | float] = {}
    for key in ("stars", "destruction", "loot_gold", "loot_elixir", "loot_dark"):
        value = getattr(args, key, None)
        if value is not None:
            result[key] = value
    return result or None


def _prompt_attack_result(result: dict[str, int | float] | None) -> dict[str, int | float] | None:
    prompted = dict(result or {})
    prompts = (
        ("stars", "Stars (0-3, blank to skip): ", int),
        ("destruction", "Destruction percent (0-100, blank to skip): ", float),
        ("loot_gold", "Gold loot (blank to skip): ", int),
        ("loot_elixir", "Elixir loot (blank to skip): ", int),
        ("loot_dark", "Dark elixir loot (blank to skip): ", int),
    )
    for key, prompt, caster in prompts:
        if key in prompted:
            continue
        value = input(prompt).strip()
        if not value:
            continue
        prompted[key] = caster(value)
    return prompted or None


def _select_attack_index(attacks: list[dict], raw_index: int | None) -> int:
    if not attacks:
        raise ValueError("no attacks are recorded yet")

    if raw_index is None:
        for index in range(len(attacks) - 1, -1, -1):
            if attacks[index].get("score") is None:
                return index
        return len(attacks) - 1

    if raw_index == 0:
        raise ValueError("--attack-index is 1-based; use 1 for the first attack or -1 for the latest")
    index = raw_index - 1 if raw_index > 0 else len(attacks) + raw_index
    if index < 0 or index >= len(attacks):
        raise ValueError(f"--attack-index {raw_index} is outside the recorded attack range 1..{len(attacks)}")
    return index


def cmd_attack(args: argparse.Namespace) -> int:
    profile = load_json(args.profile)
    display_id = _resolve_display(args, profile)
    adb = _adb_from_args(args, display_id)
    runner = MacroRunner(
        adb,
        profile,
        base_dir=Path.cwd(),
        dry_run=args.dry_run,
    )

    learning_state = load_learning_state(args.learning_state)
    forced_strategy = args.strategy
    if args.routine:
        strategy_name = args.strategy or Path(args.routine).stem
        forced_strategy = strategy_name
        learning_state["strategies"] = [
            *[s for s in learning_state.get("strategies", []) if not isinstance(s, dict) or s.get("name") != strategy_name],
            {"name": strategy_name, "routine": args.routine, "base_score": 0},
        ]

    for i in range(args.repeat):
        if args.repeat > 1:
            print(f"attack cycle {i + 1}/{args.repeat}")

        strategy = choose_strategy(learning_state, forced_strategy)
        routine_path = _routine_path(args.routines_dir, str(strategy.get("routine", "")))
        print(f"selected strategy: {strategy.get('name', routine_path.stem)} ({routine_path})")
        routine = load_json(routine_path)

        started_at = timestamp()
        runner.run(routine)
        if args.result_wait > 0:
            print(f"waiting {args.result_wait:.1f}s for attack result")
            if not args.dry_run:
                time.sleep(args.result_wait)

        screenshots: list[str] = []
        result_screenshot = args.post_screenshot
        if not result_screenshot:
            stamp = started_at.replace(":", "").replace("-", "")
            result_screenshot = str(Path("screenshots") / "attack_results" / f"{stamp}_{safe_name(str(strategy.get('name', 'attack')))}.png")
        out = Path(result_screenshot)
        print(f"result screenshot {out}")
        adb.screencap(out)
        screenshots.append(str(out))

        result = _attack_result_from_args(args)
        if args.prompt_result and not args.dry_run:
            result = _prompt_attack_result(result)

        attack = record_attack(
            learning_state,
            strategy=strategy,
            profile=args.profile,
            result=result,
            screenshots=screenshots,
            started_at=started_at,
            ended_at=timestamp(),
            dry_run=args.dry_run,
        )
        if attack["score"] is None:
            print("recorded attack without score; pass --stars/--destruction or use --prompt-result to train ranking")
        else:
            print(f"recorded attack score={attack['score']}")

        if i + 1 < args.repeat and args.delay > 0 and not args.dry_run:
            time.sleep(args.delay)

    if not args.dry_run:
        save_learning_state(args.learning_state, learning_state)
        print(f"saved learning state: {args.learning_state}")
    else:
        print("dry-run: learning state was not saved")
    return 0


def cmd_attack_stats(args: argparse.Namespace) -> int:
    state = load_learning_state(args.learning_state)
    strategies = strategy_summary(state)
    if not strategies:
        print("no attack strategies configured")
        return 0
    for strategy in strategies:
        avg = strategy.get("average_score")
        avg_text = f"{avg:.2f}" if isinstance(avg, (int, float)) else "unscored"
        print(
            f"{strategy.get('name', strategy.get('routine', 'strategy'))}: "
            f"attempts={strategy.get('attempts', 0)}, "
            f"scored={strategy.get('scored_attempts', 0)}, "
            f"avg={avg_text}, "
            f"best={strategy.get('best_score')}"
        )
    attacks = [a for a in state.get("attacks", []) if isinstance(a, dict)]
    if attacks:
        print("recent attacks:")
        start = max(0, len(attacks) - 5)
        for index, attack in enumerate(attacks[start:], start=start + 1):
            print(
                f"  #{index} {attack.get('ended_at')}: {attack.get('strategy')} "
                f"score={attack.get('score')} result={attack.get('result', {})}"
            )
    return 0


def cmd_record_result(args: argparse.Namespace) -> int:
    state = load_learning_state(args.learning_state)
    attacks = [a for a in state.get("attacks", []) if isinstance(a, dict)]
    try:
        index = _select_attack_index(attacks, args.attack_index)
    except ValueError as exc:
        print(exc)
        return 2
    attack = attacks[index]

    result = _attack_result_from_args(args)
    if args.prompt_result:
        result = _prompt_attack_result(result)
    if not result:
        print("no result fields provided; pass --stars/--destruction/loot values or use --prompt-result")
        return 2

    merged = dict(attack.get("result", {}) if isinstance(attack.get("result"), dict) else {})
    merged.update(result)
    attack["result"] = merged
    attack["result_recorded_at"] = timestamp()

    score = result_score(merged)
    attack["score"] = round(score, 2) if score is not None else None
    recompute_strategy_stats(state)
    save_learning_state(args.learning_state, state)

    print(
        f"updated attack #{index + 1}: {attack.get('strategy')} "
        f"score={attack.get('score')} result={attack.get('result', {})}"
    )
    print(f"saved learning state: {args.learning_state}")
    return 0


def cmd_upgrade(args: argparse.Namespace) -> int:
    state = load_json(args.state)
    profile = load_json(args.profile)
    display_id = _resolve_display(args, profile)
    plan = plan_upgrades(state, args.max)
    if not plan:
        print("no affordable upgrades matched the current constraints")
        return 0

    adb = _adb_from_args(args, display_id)
    runner = MacroRunner(
        adb,
        profile,
        base_dir=Path.cwd(),
        dry_run=args.dry_run,
    )

    for i, upgrade in enumerate(plan, start=1):
        if not upgrade.routine:
            print(f"{i}. {upgrade.name}: no routine configured, skipping")
            continue
        path = _routine_path(args.routines_dir, upgrade.routine)
        print(f"{i}. {upgrade.name}: {path}")
        routine = load_json(path)
        runner.run(routine)
    return 0


def _return_home_after_attack(args: argparse.Namespace) -> None:
    presses = int(getattr(args, "return_home_presses", 1))
    if presses <= 0:
        return

    delay = float(getattr(args, "return_home_delay", 2.0))
    profile = load_json(args.profile)
    display_id = _resolve_display(args, profile)
    adb = _adb_from_args(args, display_id)

    for i in range(presses):
        print(f"return home: BACK {i + 1}/{presses}")
        adb.keyevent("BACK")
        if delay > 0 and not getattr(args, "dry_run", False):
            time.sleep(delay)


def cmd_farm_cycle(args: argparse.Namespace) -> int:
    for i in range(args.cycles):
        print(f"farm cycle {i + 1}/{args.cycles}: attack")
        attack_args = argparse.Namespace(
            adb=args.adb,
            serial=args.serial,
            profile=args.profile,
            learning_state=args.learning_state,
            routines_dir=args.routines_dir,
            routine=args.attack_routine,
            strategy=args.strategy,
            display=args.display,
            repeat=1,
            delay=0.0,
            result_wait=args.result_wait,
            post_screenshot=None,
            stars=None,
            destruction=None,
            loot_gold=None,
            loot_elixir=None,
            loot_dark=None,
            prompt_result=args.prompt_result,
            dry_run=args.dry_run,
        )
        result = cmd_attack(attack_args)
        if result:
            return result

        if not args.skip_return_home:
            _return_home_after_attack(args)

        should_upgrade = not args.skip_upgrade and (i + 1) % max(1, args.upgrade_every) == 0
        if should_upgrade:
            print(f"farm cycle {i + 1}/{args.cycles}: auto-upgrade")
            upgrade_args = argparse.Namespace(
                adb=args.adb,
                serial=args.serial,
                state=args.upgrade_state,
                profile=args.profile,
                routines_dir=args.routines_dir,
                max=args.upgrade_max,
                display=args.display,
                dry_run=args.dry_run,
            )
            result = cmd_upgrade(upgrade_args)
            if result:
                return result

        if i + 1 < args.cycles and args.delay > 0 and not args.dry_run:
            time.sleep(args.delay)

    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    from .gui import run as run_gui

    return run_gui(args)


def cmd_wheel_zoom(args: argparse.Namespace) -> int:
    from .wheel_zoom import run as run_wheel_zoom

    return run_wheel_zoom(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python3 -m clashbot")
    parser.add_argument("--adb", default=None, help="path to adb; defaults to $ADB or PATH")
    parser.add_argument("--serial", default=None, help="ADB device/emulator serial")

    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("devices", help="list connected ADB devices")
    p.set_defaults(func=cmd_devices)

    p = sub.add_parser("launch", help="launch the APK by package name")
    p.add_argument("package")
    p.add_argument("--activity", default=None)
    p.add_argument("--display", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_launch)

    p = sub.add_parser("screenshot", help="save a PNG screenshot through adb")
    p.add_argument("--out", default="screenshots/screen.png")
    p.add_argument("--display", default=None)
    p.add_argument("--profile", default=None, help="profile to use for display auto-detection")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_screenshot)

    p = sub.add_parser("tap", help="tap a raw pixel coordinate")
    p.add_argument("x", type=int)
    p.add_argument("y", type=int)
    p.add_argument("--display", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_tap)

    p = sub.add_parser("zoom-out", help="pinch the Clash camera out to a wider view")
    p.add_argument("--profile", default="profiles/clash_1600x900_display_auto.json")
    p.add_argument("--display", default=None)
    p.add_argument("--steps", type=int, default=8)
    p.add_argument("--duration-ms", type=int, default=450)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_zoom_out)

    p = sub.add_parser("run", help="run a calibrated JSON routine")
    p.add_argument("--profile", required=True)
    p.add_argument("--routine", required=True)
    p.add_argument("--display", default=None)
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--delay", type=float, default=3.0, help="seconds between repeated runs")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("plan", help="rank local village upgrades from a state JSON file")
    p.add_argument("--state", required=True)
    p.add_argument("--max", type=int, default=None)
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("upgrade", help="plan upgrades, then run each selected upgrade routine")
    p.add_argument("--state", required=True)
    p.add_argument("--profile", required=True)
    p.add_argument("--routines-dir", default="routines")
    p.add_argument("--max", type=int, default=None)
    p.add_argument("--display", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_upgrade)

    p = sub.add_parser("attack", help="run an attack routine and update local learning stats")
    p.add_argument("--profile", required=True)
    p.add_argument("--learning-state", default="state/attack_learning.json")
    p.add_argument("--routines-dir", default="routines")
    p.add_argument("--routine", default=None, help="force/add a routine for this run")
    p.add_argument("--strategy", default=None, help="force a configured strategy name")
    p.add_argument("--display", default=None)
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--delay", type=float, default=10.0, help="seconds between repeated attacks")
    p.add_argument("--result-wait", type=float, default=8.0, help="seconds to wait before taking result screenshot")
    p.add_argument("--post-screenshot", default=None)
    p.add_argument("--stars", type=int, choices=range(0, 4), default=None)
    p.add_argument("--destruction", type=float, default=None)
    p.add_argument("--loot-gold", type=int, default=None)
    p.add_argument("--loot-elixir", type=int, default=None)
    p.add_argument("--loot-dark", type=int, default=None)
    p.add_argument("--prompt-result", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_attack)

    p = sub.add_parser("attack-stats", help="show learned attack routine performance")
    p.add_argument("--learning-state", default="state/attack_learning.json")
    p.set_defaults(func=cmd_attack_stats)

    p = sub.add_parser("record-result", help="attach an observed result to a previous attack")
    p.add_argument("--learning-state", default="state/attack_learning.json")
    p.add_argument("--attack-index", type=int, default=None, help="1-based attack number from attack-stats; default latest unscored")
    p.add_argument("--stars", type=int, choices=range(0, 4), default=None)
    p.add_argument("--destruction", type=float, default=None)
    p.add_argument("--loot-gold", type=int, default=None)
    p.add_argument("--loot-elixir", type=int, default=None)
    p.add_argument("--loot-dark", type=int, default=None)
    p.add_argument("--prompt-result", action="store_true")
    p.set_defaults(func=cmd_record_result)

    p = sub.add_parser("farm-cycle", help="run E-Drag farming attacks and auto-upgrade afterward")
    p.add_argument("--profile", required=True)
    p.add_argument("--learning-state", default="state/attack_learning.json")
    p.add_argument("--routines-dir", default="routines")
    p.add_argument("--attack-routine", default="routines/clash_attack_edrag_bottom_push_widescreen.json")
    p.add_argument("--strategy", default="edrag_funnel")
    p.add_argument("--display", default=None)
    p.add_argument("--cycles", type=int, default=1)
    p.add_argument("--delay", type=float, default=10.0, help="seconds between farm cycles")
    p.add_argument("--result-wait", type=float, default=185.0, help="seconds to wait before result screenshot/return")
    p.add_argument("--prompt-result", action="store_true", help="prompt for stars/destruction/loot after each attack")
    p.add_argument("--skip-return-home", action="store_true", help="do not press BACK after each attack result")
    p.add_argument("--return-home-presses", type=int, default=1)
    p.add_argument("--return-home-delay", type=float, default=2.0)
    p.add_argument("--skip-upgrade", action="store_true", help="do not run the upgrade planner after attacks")
    p.add_argument("--upgrade-every", type=int, default=1, help="run upgrade planner every N attacks")
    p.add_argument("--upgrade-state", default="state/village_state.example.json")
    p.add_argument("--upgrade-max", type=int, default=1)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_farm_cycle)

    p = sub.add_parser("gui", help="open the Clashbot overlay control panel")
    p.add_argument("--profile", default="profiles/clash_1600x900_display_auto.json")
    p.add_argument("--routine", default="routines/clash_attack_edrag_bottom_push_widescreen.json")
    p.add_argument("--upgrade-state", default="state/village_state.example.json")
    p.add_argument("--display", default=None)
    p.add_argument("--cycles", type=int, default=1)
    p.add_argument("--delay", type=float, default=10.0)
    p.add_argument("--result-wait", type=float, default=185.0)
    p.add_argument("--upgrade-every", type=int, default=1)
    p.add_argument("--upgrade-max", type=int, default=1)
    p.add_argument("--window-title", default="Clash of Clans")
    p.set_defaults(func=cmd_gui)

    p = sub.add_parser("wheel-zoom", help="map mouse wheel over Clash to camera zoom")
    p.add_argument("--profile", default="profiles/clash_1600x900_display_auto.json")
    p.add_argument("--display", default=None)
    p.add_argument("--window-title", default="Clash of Clans")
    p.add_argument("--duration-ms", type=int, default=260)
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument("--replace", action="store_true", help="stop old wheel helpers before grabbing the wheel")
    p.set_defaults(func=cmd_wheel_zoom)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
