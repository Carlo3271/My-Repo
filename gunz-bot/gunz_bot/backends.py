from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Iterable


class BackendError(RuntimeError):
    pass


class InputBackend:
    name = "base"

    def focus_window(self, window_name: str) -> str | None:
        raise NotImplementedError

    def key_down(self, key: str) -> None:
        raise NotImplementedError

    def key_up(self, key: str) -> None:
        raise NotImplementedError

    def mouse_down(self, button: int) -> None:
        raise NotImplementedError

    def mouse_up(self, button: int) -> None:
        raise NotImplementedError

    def move_mouse(self, dx: int, dy: int) -> None:
        raise NotImplementedError

    def sleep(self, seconds: float) -> None:
        time.sleep(max(0.0, seconds))

    def release_all(self, keys: Iterable[str], mouse_buttons: Iterable[int]) -> None:
        for key in sorted(set(k for k in keys if k)):
            try:
                self.key_up(key)
            except BackendError:
                pass
        for button in sorted(set(mouse_buttons)):
            try:
                self.mouse_up(button)
            except BackendError:
                pass


class DryRunBackend(InputBackend):
    name = "dry-run"

    def __init__(self, sleep_enabled: bool = False) -> None:
        self.sleep_enabled = sleep_enabled

    def focus_window(self, window_name: str) -> str | None:
        print(f"[dry-run] focus window matching: {window_name}")
        return None

    def key_down(self, key: str) -> None:
        print(f"[dry-run] key down: {key}")

    def key_up(self, key: str) -> None:
        print(f"[dry-run] key up: {key}")

    def mouse_down(self, button: int) -> None:
        print(f"[dry-run] mouse down: {button}")

    def mouse_up(self, button: int) -> None:
        print(f"[dry-run] mouse up: {button}")

    def move_mouse(self, dx: int, dy: int) -> None:
        print(f"[dry-run] mouse move: dx={dx} dy={dy}")

    def sleep(self, seconds: float) -> None:
        print(f"[dry-run] wait: {seconds:.3f}s")
        if self.sleep_enabled:
            super().sleep(seconds)


class XDoToolBackend(InputBackend):
    name = "xdotool"

    def __init__(self) -> None:
        self.binary = shutil.which("xdotool")
        if not self.binary:
            raise BackendError(
                "xdotool is not installed. Run scripts/install_deps_arch.sh, "
                "or use --dry-run to test without sending input."
            )

    @staticmethod
    def available() -> bool:
        return shutil.which("xdotool") is not None

    def _run(self, *args: str | int) -> str:
        cmd = [self.binary or "xdotool", *[str(arg) for arg in args]]
        completed = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise BackendError(f"xdotool failed: {' '.join(cmd)}\n{detail}")
        return completed.stdout.strip()

    def focus_window(self, window_name: str) -> str | None:
        matches = self._run("search", "--onlyvisible", "--name", window_name).splitlines()
        if not matches:
            raise BackendError(f"No visible window matched {window_name!r}.")
        window_id = matches[-1]
        self._run("windowactivate", "--sync", window_id)
        return window_id

    def key_down(self, key: str) -> None:
        self._run("keydown", "--clearmodifiers", key)

    def key_up(self, key: str) -> None:
        self._run("keyup", "--clearmodifiers", key)

    def mouse_down(self, button: int) -> None:
        self._run("mousedown", button)

    def mouse_up(self, button: int) -> None:
        self._run("mouseup", button)

    def move_mouse(self, dx: int, dy: int) -> None:
        self._run("mousemove_relative", "--", dx, dy)
