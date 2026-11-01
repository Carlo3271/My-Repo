from __future__ import annotations

import argparse
import shutil
import sys

from .backends import BackendError, DryRunBackend, XDoToolBackend
from .combos import (
    TECHNIQUE_DESCRIPTIONS,
    build_demo,
    build_technique,
    cycles_for_seconds,
    estimate_seconds,
)
from .config import DEFAULT_CONFIG, PROJECT_ROOT, load_config
from .learn import learn_technique
from .runner import countdown, release_keys, release_mouse_buttons, safe_execute


DIRECTIONS = ["left", "right", "forward", "back", "alternate"]


def make_backend(dry_run: bool, dry_run_sleep: bool = False):
    if dry_run:
        return DryRunBackend(sleep_enabled=dry_run_sleep)
    return XDoToolBackend()


def add_runtime_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Path to config JSON.")
    parser.add_argument("--profile", help="Optional learned profile JSON to merge over config.")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without sending input.")
    parser.add_argument("--dry-run-sleep", action="store_true", help="Sleep during dry-run waits.")
    parser.add_argument("--no-focus", action="store_true", help="Do not focus the GunZ window first.")
    parser.add_argument("--window-name", help="xdotool window name search pattern.")
    parser.add_argument("--countdown", type=float, help="Seconds to wait before running.")
    parser.add_argument("--speed", type=float, default=1.0, help="Timing multiplier. 1.2 is faster, 0.8 is slower.")


def load_runtime_config(args: argparse.Namespace) -> dict:
    config = load_config(args.config, args.profile)
    if args.window_name:
        config["window_name"] = args.window_name
    if args.countdown is not None:
        config["countdown_seconds"] = args.countdown
    return config


def prepare_game(args: argparse.Namespace, config: dict, backend) -> None:
    if not args.no_focus:
        backend.focus_window(str(config["window_name"]))
    if float(config.get("countdown_seconds", 0)) > 0:
        countdown(float(config["countdown_seconds"]))


def cmd_check(args: argparse.Namespace) -> int:
    config = load_runtime_config(args)
    print(f"Project: {PROJECT_ROOT}")
    print(f"Config: {args.config}")
    if args.profile:
        print(f"Profile: {args.profile}")
    print(f"Python: {sys.version.split()[0]}")
    print(f"xdotool: {shutil.which('xdotool') or 'missing'}")
    print(f"Window pattern: {config['window_name']}")
    if args.dry_run:
        print("Dry run selected: no input will be sent.")
        return 0
    if not XDoToolBackend.available():
        print("Install xdotool before real runs: scripts/install_deps_arch.sh")
        return 1
    backend = XDoToolBackend()
    if not args.no_focus:
        window_id = backend.focus_window(str(config["window_name"]))
        print(f"Focused window id: {window_id}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    for name, description in TECHNIQUE_DESCRIPTIONS.items():
        print(f"{name:12} {description}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    config = load_runtime_config(args)
    backend = make_backend(args.dry_run, args.dry_run_sleep)
    cycles = args.cycles
    if args.seconds is not None:
        cycles = cycles_for_seconds(config, args.technique, args.seconds, args.direction)

    actions = build_technique(config, args.technique, cycles, args.direction)
    print(
        f"Running {args.technique}: cycles={cycles}, "
        f"estimated_input_time={estimate_seconds(actions):.2f}s, backend={backend.name}"
    )
    prepare_game(args, config, backend)
    safe_execute(actions, backend, config, speed=args.speed)
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    config = load_runtime_config(args)
    backend = make_backend(args.dry_run, args.dry_run_sleep)
    actions = build_demo(config, args.cycles, args.direction)
    print(
        f"Running demo take: cycles_per_technique={args.cycles}, "
        f"estimated_input_time={estimate_seconds(actions):.2f}s, backend={backend.name}"
    )
    prepare_game(args, config, backend)
    safe_execute(actions, backend, config, speed=args.speed)
    return 0


def cmd_learn(args: argparse.Namespace) -> int:
    config = load_runtime_config(args)
    backend = make_backend(args.dry_run, args.dry_run_sleep)
    profile = learn_technique(
        config=config,
        backend=backend,
        technique=args.technique,
        trials=args.trials,
        cycles=args.cycles,
        direction=args.direction,
        speed=args.speed,
        window_name=str(config["window_name"]),
        no_focus=args.no_focus,
        initial_countdown=float(config.get("countdown_seconds", 0)),
        trial_gap=args.trial_gap,
        auto_score=args.auto_score,
    )
    print(f"Saved learned profile: {profile}")
    return 0


def cmd_release(args: argparse.Namespace) -> int:
    config = load_runtime_config(args)
    backend = make_backend(args.dry_run, args.dry_run_sleep)
    backend.release_all(release_keys(config), release_mouse_buttons(config))
    print("Released configured keys and mouse buttons.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gunz-bot",
        description="Private-room GunZ K-style input bot and timing learner.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="Check dependencies and optionally focus GunZ.")
    add_runtime_args(check)
    check.set_defaults(func=cmd_check)

    list_cmd = subparsers.add_parser("list", help="List available K-style routines.")
    list_cmd.set_defaults(func=cmd_list)

    run = subparsers.add_parser("run", help="Run one K-style routine.")
    add_runtime_args(run)
    run.add_argument("technique", choices=sorted(TECHNIQUE_DESCRIPTIONS))
    run.add_argument("--cycles", type=int, default=6)
    run.add_argument("--seconds", type=float)
    run.add_argument("--direction", choices=DIRECTIONS, default="alternate")
    run.set_defaults(func=cmd_run)

    demo = subparsers.add_parser("demo", help="Run a video-friendly sequence of routines.")
    add_runtime_args(demo)
    demo.add_argument("--cycles", type=int, default=4)
    demo.add_argument("--direction", choices=DIRECTIONS, default="alternate")
    demo.set_defaults(func=cmd_demo)

    learn = subparsers.add_parser("learn", help="Tune routine timings from human scores.")
    add_runtime_args(learn)
    learn.add_argument("technique", choices=sorted(name for name in TECHNIQUE_DESCRIPTIONS if name != "spar"))
    learn.add_argument("--trials", type=int, default=25)
    learn.add_argument("--cycles", type=int, default=3)
    learn.add_argument("--direction", choices=DIRECTIONS, default="alternate")
    learn.add_argument("--trial-gap", type=float, default=0.8)
    learn.add_argument("--auto-score", type=float, help="Testing only: use a fixed score instead of prompting.")
    learn.set_defaults(func=cmd_learn)

    release = subparsers.add_parser("release", help="Release configured keys and mouse buttons.")
    add_runtime_args(release)
    release.set_defaults(func=cmd_release)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except BackendError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
