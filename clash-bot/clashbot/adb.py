from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Iterable


class ADBError(RuntimeError):
    pass


class ADB:
    def __init__(
        self,
        adb_path: str | None = None,
        serial: str | None = None,
        display_id: int | None = None,
        dry_run: bool = False,
        timeout: float = 30,
    ) -> None:
        self.adb_path = adb_path or os.environ.get("ADB") or shutil.which("adb") or "/home/carlo/.local/bin/adb"
        self.serial = serial
        self.display_id = display_id
        self.dry_run = dry_run
        self.timeout = timeout

    def _cmd(self, args: Iterable[str]) -> list[str]:
        cmd = [self.adb_path]
        if self.serial:
            cmd += ["-s", self.serial]
        cmd += list(args)
        return cmd

    def run(
        self,
        args: Iterable[str],
        *,
        check: bool = True,
        text: bool = True,
        stdout: int | None = subprocess.PIPE,
    ) -> subprocess.CompletedProcess:
        cmd = self._cmd(args)
        if self.dry_run:
            print("$ " + " ".join(cmd))
            return subprocess.CompletedProcess(cmd, 0, "" if text else b"", "")

        try:
            proc = subprocess.run(
                cmd,
                check=False,
                text=text,
                stdout=stdout,
                stderr=subprocess.PIPE,
                timeout=self.timeout,
            )
        except FileNotFoundError as exc:
            raise ADBError(f"adb not found at {self.adb_path!r}") from exc

        if check and proc.returncode != 0:
            err = proc.stderr.decode(errors="replace") if isinstance(proc.stderr, bytes) else proc.stderr
            raise ADBError(f"adb command failed ({proc.returncode}): {' '.join(cmd)}\n{err.strip()}")
        return proc

    def devices(self) -> list[tuple[str, str]]:
        proc = self.run(["devices"], text=True)
        devices: list[tuple[str, str]] = []
        for line in proc.stdout.splitlines()[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                devices.append((parts[0], parts[1]))
        return devices

    def shell(self, *args: object) -> str:
        proc = self.run(["shell", *map(str, args)], text=True)
        return proc.stdout

    def wm_size(self) -> tuple[int, int]:
        out = self.shell("wm", "size")
        match = re.search(r"(\d+)x(\d+)", out)
        if not match:
            raise ADBError(f"could not parse screen size from: {out!r}")
        return int(match.group(1)), int(match.group(2))

    def detect_display_id(
        self,
        package: str,
        *,
        size: tuple[int, int] | None = None,
    ) -> int:
        out = self.shell("dumpsys", "window")
        candidates: list[tuple[int, int, int, bool]] = []

        for section in re.split(r"\n\s*Window #\d+ ", out):
            if package not in section:
                continue
            display = re.search(r"\bmDisplayId=(\d+)", section)
            if not display:
                continue
            requested = re.search(r"\bRequested w=(\d+) h=(\d+)", section)
            visible = "isVisible=true" in section or "isOnScreen=true" in section
            width = int(requested.group(1)) if requested else 0
            height = int(requested.group(2)) if requested else 0
            candidates.append((int(display.group(1)), width, height, visible))

        if size:
            for display_id, width, height, _visible in candidates:
                if (width, height) == size:
                    return display_id

        for display_id, _width, _height, visible in candidates:
            if visible:
                return display_id

        if candidates:
            return candidates[0][0]

        focused = re.search(r"\bmTopFocusedDisplayId=(\d+)", out)
        if focused:
            return int(focused.group(1))

        raise ADBError(f"could not detect display id for package {package!r}")

    def _input_args(self, command: str, *args: object) -> list[str]:
        cmd = ["shell", "input"]
        if self.display_id is not None:
            cmd += ["-d", str(self.display_id)]
        cmd += [command, *map(str, args)]
        return cmd

    def tap(self, x: int, y: int) -> None:
        self.run(self._input_args("tap", x, y), stdout=None)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 350) -> None:
        self.run(self._input_args("swipe", x1, y1, x2, y2, duration_ms), stdout=None)

    def pinch(
        self,
        start1: tuple[int, int],
        end1: tuple[int, int],
        start2: tuple[int, int],
        end2: tuple[int, int],
        *,
        duration_ms: int = 450,
    ) -> None:
        display = f" -d {self.display_id}" if self.display_id is not None else ""
        command = (
            f"input touchscreen{display} swipe {start1[0]} {start1[1]} {end1[0]} {end1[1]} {duration_ms} & "
            f"input touchscreen{display} swipe {start2[0]} {start2[1]} {end2[0]} {end2[1]} {duration_ms} & "
            "wait"
        )
        if self.dry_run:
            print("$ " + " ".join(self._cmd(["shell", command])))
            return
        self.run(["shell", command], stdout=None)

    def zoom_out(self, width: int, height: int, *, steps: int = 6, duration_ms: int = 450) -> None:
        for _ in range(max(1, steps)):
            self.pinch(
                (round(width * 0.18), round(height * 0.50)),
                (round(width * 0.46), round(height * 0.50)),
                (round(width * 0.82), round(height * 0.50)),
                (round(width * 0.54), round(height * 0.50)),
                duration_ms=duration_ms,
            )
            if not self.dry_run:
                time.sleep(0.12)

    def zoom_in(self, width: int, height: int, *, steps: int = 1, duration_ms: int = 350) -> None:
        for _ in range(max(1, steps)):
            self.pinch(
                (round(width * 0.46), round(height * 0.50)),
                (round(width * 0.18), round(height * 0.50)),
                (round(width * 0.54), round(height * 0.50)),
                (round(width * 0.82), round(height * 0.50)),
                duration_ms=duration_ms,
            )
            if not self.dry_run:
                time.sleep(0.08)

    def mouse_roll(self, dx: int, dy: int) -> None:
        cmd = ["shell", "input", "mouse"]
        if self.display_id is not None:
            cmd += ["-d", str(self.display_id)]
        cmd += ["roll", str(dx), str(dy)]
        self.run(cmd, stdout=None)

    def keyevent(self, key: str | int) -> None:
        self.run(self._input_args("keyevent", key), stdout=None)

    def launch(self, package: str, activity: str | None = None) -> None:
        if activity:
            self.run(["shell", "am", "start", "-n", f"{package}/{activity}"], stdout=None)
        else:
            self.run(
                ["shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"],
                stdout=None,
            )

    def screencap(self, out_path: str | Path, display_id: int | None = None) -> Path:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        target_display = self.display_id if display_id is None else display_id
        if self.dry_run:
            display = f" from display {target_display}" if target_display is not None else ""
            print(f"# would write screenshot{display} to {out}")
            return out
        args = ["exec-out", "screencap"]
        if target_display is not None:
            args += ["-d", str(target_display)]
        args.append("-p")
        proc = self.run(args, text=False)
        out.write_bytes(proc.stdout)
        return out
