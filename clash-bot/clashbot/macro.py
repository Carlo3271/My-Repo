from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .adb import ADB
from .config import screen_from_profile
from .geometry import resolve_point
from .perimeter import DeploymentPerimeter, auto_adjust_anchor
from .screen_checks import troop_bar_visible


class MacroRunner:
    def __init__(
        self,
        adb: ADB,
        profile: dict[str, Any],
        *,
        base_dir: str | Path = ".",
        screen: tuple[int, int] | None = None,
        dry_run: bool = False,
    ) -> None:
        self.adb = adb
        self.profile = profile
        self.base_dir = Path(base_dir)
        self.screen = screen or screen_from_profile(profile)
        self.dry_run = dry_run
        self._perimeter: DeploymentPerimeter | None = None

    def get_screen(self) -> tuple[int, int]:
        if self.screen:
            return self.screen
        if self.dry_run:
            self.screen = (1080, 1920)
            return self.screen
        self.screen = self.adb.wm_size()
        return self.screen

    def run(self, routine: dict[str, Any]) -> None:
        self._perimeter = None
        steps = routine.get("steps")
        if not isinstance(steps, list):
            raise ValueError("routine must contain a 'steps' list")
        print(f"running routine: {routine.get('name', 'unnamed')}")
        self._run_steps(steps)

    def _run_steps(self, steps: list[Any]) -> None:
        for index, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                raise ValueError(f"step {index} must be an object")
            self._run_step(step, index)

    def _run_step(self, step: dict[str, Any], index: int) -> None:
        label = step.get("label")
        if label:
            print(f"[{index}] {label}")

        if "repeat" in step:
            count = int(step["repeat"])
            nested = step.get("steps")
            if not isinstance(nested, list):
                raise ValueError("repeat step must contain a 'steps' list")
            for i in range(count):
                print(f"  repeat {i + 1}/{count}")
                self._run_steps(nested)
            return

        if "ensure_battle" in step:
            self._ensure_battle(step)
            return

        if "tap" in step:
            x, y = self._resolve_tap(step["tap"])
            print(f"  tap {x},{y}")
            self.adb.tap(x, y)
            self._wait_after(step)
            return

        if "swipe" in step:
            swipe = step["swipe"]
            start = resolve_point(swipe["from"], self.profile, self.get_screen())
            end = resolve_point(swipe["to"], self.profile, self.get_screen())
            duration = int(swipe.get("duration_ms", 350))
            print(f"  swipe {start[0]},{start[1]} -> {end[0]},{end[1]} ({duration}ms)")
            self.adb.swipe(start[0], start[1], end[0], end[1], duration)
            self._wait_after(step)
            return

        if "wait" in step:
            seconds = float(step["wait"])
            print(f"  wait {seconds:.2f}s")
            if not self.dry_run:
                time.sleep(seconds)
            return

        if "wait_for" in step:
            self._wait_for(step)
            return

        if "keyevent" in step:
            key = step["keyevent"]
            print(f"  keyevent {key}")
            self.adb.keyevent(key)
            self._wait_after(step)
            return

        if "screenshot" in step:
            out = self.base_dir / str(step["screenshot"])
            print(f"  screenshot {out}")
            self.adb.screencap(out)
            self._wait_after(step)
            return

        raise ValueError(f"unknown step: {step}")

    def _resolve_tap(self, target: Any) -> tuple[int, int]:
        point = resolve_point(target, self.profile, self.get_screen())
        anchor = auto_adjust_anchor(target, self.profile)
        if not anchor:
            return point

        if self.dry_run:
            print("  auto-perimeter: dry-run uses static anchor")
            return point

        if self._perimeter is None:
            deployment = self.profile.get("deployment", {})
            if not isinstance(deployment, dict):
                deployment = {}
            screenshot = self.base_dir / str(deployment.get("perimeter_screenshot", "screenshots/perimeter_live.png"))
            print(f"  auto-perimeter: screenshot {screenshot}")
            self.adb.screencap(screenshot)
            self._perimeter = DeploymentPerimeter.from_image(screenshot, self.profile, self.get_screen())

        adjusted = self._perimeter.resolve(anchor, point)
        if adjusted != point:
            print(f"  auto-perimeter: {anchor} {point[0]},{point[1]} -> {adjusted[0]},{adjusted[1]}")
        return adjusted

    def _wait_after(self, step: dict[str, Any]) -> None:
        wait = step.get("wait_after")
        if wait is not None and not self.dry_run:
            time.sleep(float(wait))

    def _ensure_battle(self, step: dict[str, Any]) -> None:
        config = step["ensure_battle"]
        if not isinstance(config, dict):
            config = {}

        screenshot = self.base_dir / str(config.get("screenshot", "screenshots/battle_ready.png"))
        timeout = float(config.get("timeout", 12.0))
        interval = float(config.get("interval", 0.5))

        print("  ensure battle screen")
        if self.dry_run:
            print("  dry-run: would check troop bar, then open/find match if needed")
            return

        self.adb.screencap(screenshot)
        if troop_bar_visible(screenshot, self.get_screen()):
            print("  troop bar already visible")
            return

        open_anchor = str(config.get("open_attack", "home_attack"))
        find_anchor = str(config.get("find_match", "find_match"))
        open_wait = float(config.get("open_wait", 1.4))
        find_wait = float(config.get("find_wait", 0.8))
        find_retries = int(config.get("find_retries", 3))
        find_retry_interval = float(config.get("find_retry_interval", 1.5))

        x, y = resolve_point(open_anchor, self.profile, self.get_screen())
        print(f"  open attack {x},{y}")
        self.adb.tap(x, y)
        time.sleep(open_wait)

        x, y = resolve_point(find_anchor, self.profile, self.get_screen())
        print(f"  find match {x},{y}")
        self.adb.tap(x, y)
        time.sleep(find_wait)

        deadline = time.monotonic() + timeout
        attempt = 0
        next_retry = time.monotonic() + find_retry_interval
        while True:
            attempt += 1
            self.adb.screencap(screenshot)
            if troop_bar_visible(screenshot, self.get_screen()):
                print(f"  troop_bar visible after {attempt} check(s)")
                return
            now = time.monotonic()
            if now >= deadline:
                raise TimeoutError(f"troop_bar was not visible within {timeout:.1f}s")
            if find_retries > 0 and now >= next_retry:
                print(f"  retry find match {x},{y}")
                self.adb.tap(x, y)
                find_retries -= 1
                next_retry = time.monotonic() + find_retry_interval
                if find_wait > 0:
                    time.sleep(find_wait)
                continue
            time.sleep(interval)

    def _wait_for(self, step: dict[str, Any]) -> None:
        wait_for = step["wait_for"]
        target = wait_for if isinstance(wait_for, str) else wait_for.get("target")
        timeout = float(step.get("timeout", wait_for.get("timeout", 12.0) if isinstance(wait_for, dict) else 12.0))
        interval = float(step.get("interval", wait_for.get("interval", 0.5) if isinstance(wait_for, dict) else 0.5))
        screenshot_name = step.get(
            "screenshot",
            wait_for.get("screenshot", "screenshots/wait_for_battle_ready.png") if isinstance(wait_for, dict) else "screenshots/wait_for_battle_ready.png",
        )

        if target != "troop_bar":
            raise ValueError(f"unknown wait_for target: {target!r}")

        print(f"  wait for {target} up to {timeout:.1f}s")
        if self.dry_run:
            return

        screenshot = self.base_dir / str(screenshot_name)
        deadline = time.monotonic() + timeout
        attempt = 0
        while True:
            attempt += 1
            self.adb.screencap(screenshot)
            if troop_bar_visible(screenshot, self.get_screen()):
                print(f"  {target} visible after {attempt} check(s)")
                return
            if time.monotonic() >= deadline:
                raise TimeoutError(f"{target} was not visible within {timeout:.1f}s")
            time.sleep(interval)
