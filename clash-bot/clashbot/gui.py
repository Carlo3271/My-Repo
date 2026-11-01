from __future__ import annotations

import argparse
import os
import queue
import shlex
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

try:
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("Wnck", "3.0")
    from gi.repository import Gdk, GLib, Gtk, Wnck
except (ImportError, ValueError) as exc:  # pragma: no cover - exercised on systems without GTK.
    raise SystemExit(
        "The clashbot GUI needs PyGObject/GTK 3. Install the GTK Python bindings, "
        "or use the existing python3 -m clashbot CLI commands."
    ) from exc


PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE = "profiles/clash_1600x900_display_auto.json"
DEFAULT_ROUTINE = "routines/clash_attack_edrag_bottom_push_widescreen.json"
DEFAULT_UPGRADE_STATE = "state/village_state.example.json"


@dataclass(frozen=True)
class Mode:
    key: str
    label: str


MODES = (
    Mode("farm_cycle", "Farm cycle"),
    Mode("attack_loop", "Attack loop"),
    Mode("upgrade_loop", "Upgrade loop"),
    Mode("run_routine", "Run routine"),
    Mode("plan", "Plan upgrades"),
)


class CommandWorker:
    def __init__(
        self,
        commands: list[list[str]],
        *,
        cwd: Path,
        delays: list[float] | None,
        emit: Callable[[str], None],
        done: Callable[[int | None], None],
    ) -> None:
        self.commands = commands
        self.cwd = cwd
        self.delays = delays or []
        self.emit = emit
        self.done = done
        self.stop_requested = threading.Event()
        self.current_process: subprocess.Popen[str] | None = None
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_requested.set()
        process = self.current_process
        if process and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except PermissionError:
                process.terminate()

    def _run(self) -> None:
        final_code: int | None = 0
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        try:
            for index, command in enumerate(self.commands):
                if self.stop_requested.is_set():
                    final_code = None
                    break

                self.emit("$ " + shlex.join(command) + "\n")
                process = subprocess.Popen(
                    command,
                    cwd=self.cwd,
                    env=env,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    bufsize=1,
                    start_new_session=True,
                )
                self.current_process = process

                assert process.stdout is not None
                for line in process.stdout:
                    self.emit(line)
                    if self.stop_requested.is_set() and process.poll() is None:
                        self.stop()

                final_code = process.wait()
                self.current_process = None
                if self.stop_requested.is_set():
                    final_code = None
                    break
                self.emit(f"[exit {final_code}]\n")

                if final_code != 0 or index + 1 >= len(self.commands):
                    break

                delay = self.delays[index] if index < len(self.delays) else 0
                if delay > 0:
                    self.emit(f"waiting {delay:g}s before next loop\n")
                    end = time.monotonic() + delay
                    while time.monotonic() < end:
                        if self.stop_requested.is_set():
                            final_code = None
                            break
                        time.sleep(min(0.25, end - time.monotonic()))
                    if self.stop_requested.is_set():
                        break
        except Exception as exc:
            final_code = 1
            self.emit(f"[gui worker error] {exc}\n")
        finally:
            self.current_process = None
            self.done(final_code)


class ClashbotOverlay(Gtk.Window):
    def __init__(self, args: argparse.Namespace) -> None:
        super().__init__(title="Clashbot")
        self.args = args
        self.worker: CommandWorker | None = None
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.set_name("overlay-window")
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.stick()
        self.set_decorated(False)
        self.set_default_size(380, 520)
        self.set_resizable(False)
        self._configure_alpha()
        self._install_css()
        self._build_ui()
        self.connect("destroy", self._on_destroy)
        GLib.timeout_add(80, self._drain_log)
        GLib.timeout_add(500, self.place_over_clash)

    def _configure_alpha(self) -> None:
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual is not None and screen.is_composited():
            self.set_visual(visual)

    def _install_css(self) -> None:
        css = b"""
        #overlay-window, #root {
            background: rgba(16, 18, 22, 0.92);
            color: #f3f5f7;
        }
        #root {
            border: 1px solid rgba(255, 255, 255, 0.22);
            border-radius: 8px;
        }
        #dragbar {
            background: rgba(35, 39, 46, 0.95);
            border-radius: 8px 8px 0 0;
            padding: 6px;
        }
        #title {
            font-weight: 700;
        }
        label {
            color: #eef1f5;
        }
        entry, spinbutton, combobox, textview {
            color: #111318;
        }
        button {
            min-height: 28px;
        }
        #start-button {
            background: #2f8f5b;
            color: #ffffff;
            font-weight: 700;
        }
        #stop-button {
            background: #9b3c3c;
            color: #ffffff;
            font-weight: 700;
        }
        #status-label {
            color: #cbd3dd;
            font-size: 11px;
        }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def _build_ui(self) -> None:
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        root.set_name("root")
        root.set_border_width(8)
        self.add(root)

        dragbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        dragbar.set_name("dragbar")
        dragbar.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        dragbar.connect("button-press-event", self._begin_move)
        root.pack_start(dragbar, False, False, 0)

        title = Gtk.Label(label="Clashbot control")
        title.set_name("title")
        title.set_xalign(0)
        dragbar.pack_start(title, True, True, 0)

        place_button = Gtk.Button(label="Snap")
        place_button.set_tooltip_text("Move this panel onto the Clash window.")
        place_button.connect("clicked", lambda _button: self.place_over_clash())
        dragbar.pack_start(place_button, False, False, 0)

        close_button = Gtk.Button(label="X")
        close_button.set_tooltip_text("Close the control panel.")
        close_button.connect("clicked", lambda _button: self.destroy())
        dragbar.pack_start(close_button, False, False, 0)

        grid = Gtk.Grid(column_spacing=8, row_spacing=7)
        root.pack_start(grid, False, False, 0)

        self.mode_combo = Gtk.ComboBoxText()
        for mode in MODES:
            self.mode_combo.append(mode.key, mode.label)
        self.mode_combo.set_active_id("farm_cycle")
        self.mode_combo.connect("changed", self._on_mode_changed)
        self._grid_row(grid, 0, "Mode", self.mode_combo)

        self.profile_combo = self._file_combo("profiles", "*.json", self.args.profile or DEFAULT_PROFILE)
        self._grid_row(grid, 1, "Profile", self.profile_combo)

        self.routine_combo = self._file_combo("routines", "*.json", self.args.routine or DEFAULT_ROUTINE)
        self._grid_row(grid, 2, "Routine", self.routine_combo)

        self.state_combo = self._file_combo("state", "*.json", self.args.upgrade_state or DEFAULT_UPGRADE_STATE)
        self._grid_row(grid, 3, "Upgrade state", self.state_combo)

        self.cycles_spin = self._spin(1, 999, int(self.args.cycles or 1), 1)
        self._grid_row(grid, 4, "Cycles", self.cycles_spin)

        self.delay_spin = self._spin(0, 3600, float(self.args.delay), 1)
        self._grid_row(grid, 5, "Delay", self.delay_spin)

        self.result_wait_spin = self._spin(0, 900, float(self.args.result_wait), 5)
        self._grid_row(grid, 6, "Result wait", self.result_wait_spin)

        self.upgrade_every_spin = self._spin(1, 100, int(self.args.upgrade_every), 1)
        self._grid_row(grid, 7, "Upgrade every", self.upgrade_every_spin)

        self.upgrade_max_spin = self._spin(1, 10, int(self.args.upgrade_max), 1)
        self._grid_row(grid, 8, "Upgrade max", self.upgrade_max_spin)

        options = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.prompt_check = Gtk.CheckButton(label="Prompt result")
        self.skip_upgrade_check = Gtk.CheckButton(label="Skip upgrade")
        self.dry_run_check = Gtk.CheckButton(label="Dry run")
        options.pack_start(self.prompt_check, False, False, 0)
        options.pack_start(self.skip_upgrade_check, False, False, 0)
        options.pack_start(self.dry_run_check, False, False, 0)
        root.pack_start(options, False, False, 0)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        root.pack_start(controls, False, False, 0)

        self.start_button = Gtk.Button(label="Start")
        self.start_button.set_name("start-button")
        self.start_button.connect("clicked", self._on_start_clicked)
        controls.pack_start(self.start_button, True, True, 0)

        self.stop_button = Gtk.Button(label="Stop")
        self.stop_button.set_name("stop-button")
        self.stop_button.set_sensitive(False)
        self.stop_button.connect("clicked", self._on_stop_clicked)
        controls.pack_start(self.stop_button, True, True, 0)

        screenshot_button = Gtk.Button(label="Screenshot")
        screenshot_button.connect("clicked", self._on_screenshot_clicked)
        controls.pack_start(screenshot_button, True, True, 0)

        fov_button = Gtk.Button(label="FOV 100")
        fov_button.set_tooltip_text("Pinch the in-game camera out to the widest view.")
        fov_button.connect("clicked", self._on_fov_clicked)
        controls.pack_start(fov_button, True, True, 0)

        mirror_button = Gtk.Button(label="Mirror")
        mirror_button.set_tooltip_text("Launch /home/carlo/.local/bin/clash-phone.")
        mirror_button.connect("clicked", self._on_mirror_clicked)
        controls.pack_start(mirror_button, True, True, 0)

        self.status_label = Gtk.Label(label="Idle")
        self.status_label.set_name("status-label")
        self.status_label.set_xalign(0)
        root.pack_start(self.status_label, False, False, 0)

        log_frame = Gtk.Frame()
        root.pack_start(log_frame, True, True, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_min_content_height(130)
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        log_frame.add(scroller)

        self.log_view = Gtk.TextView()
        self.log_view.set_editable(False)
        self.log_view.set_cursor_visible(False)
        self.log_view.set_monospace(True)
        self.log_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        scroller.add(self.log_view)

        self._on_mode_changed(self.mode_combo)

    def _grid_row(self, grid: Gtk.Grid, row: int, label_text: str, widget: Gtk.Widget) -> None:
        label = Gtk.Label(label=label_text)
        label.set_xalign(0)
        grid.attach(label, 0, row, 1, 1)
        grid.attach(widget, 1, row, 1, 1)
        widget.set_hexpand(True)

    def _spin(self, lower: float, upper: float, value: float, step: float) -> Gtk.SpinButton:
        adjustment = Gtk.Adjustment(value=value, lower=lower, upper=upper, step_increment=step, page_increment=step * 5)
        spin = Gtk.SpinButton(adjustment=adjustment, climb_rate=1, digits=0 if float(step).is_integer() else 1)
        spin.set_numeric(True)
        return spin

    def _file_combo(self, folder: str, pattern: str, default: str) -> Gtk.ComboBoxText:
        combo = Gtk.ComboBoxText()
        values = [
            str(path.relative_to(PROJECT_DIR))
            for path in sorted((PROJECT_DIR / folder).glob(pattern))
            if path.is_file()
        ]
        default = self._normalize_project_path(default)
        if default not in values:
            values.insert(0, default)
        for value in values:
            combo.append_text(value)
        combo.set_active(max(0, values.index(default)))
        return combo

    def _normalize_project_path(self, value: str | None) -> str:
        if not value:
            return ""
        path = Path(value)
        if path.is_absolute():
            try:
                return str(path.relative_to(PROJECT_DIR))
            except ValueError:
                return str(path)
        return str(path)

    def _begin_move(self, _widget: Gtk.Widget, event: Gdk.EventButton) -> bool:
        if event.button == 1:
            self.begin_move_drag(event.button, int(event.x_root), int(event.y_root), event.time)
            return True
        return False

    def _on_mode_changed(self, _combo: Gtk.ComboBoxText) -> None:
        mode = self.mode_combo.get_active_id() or "farm_cycle"
        uses_routine = mode in {"farm_cycle", "attack_loop", "run_routine"}
        uses_upgrade = mode in {"farm_cycle", "upgrade_loop", "plan"}
        self.routine_combo.set_sensitive(uses_routine)
        self.state_combo.set_sensitive(uses_upgrade)
        self.cycles_spin.set_sensitive(mode != "plan")
        self.delay_spin.set_sensitive(mode in {"farm_cycle", "attack_loop", "upgrade_loop", "run_routine"})
        self.result_wait_spin.set_sensitive(mode in {"farm_cycle", "attack_loop"})
        self.upgrade_every_spin.set_sensitive(mode == "farm_cycle")
        self.upgrade_max_spin.set_sensitive(uses_upgrade)
        self.prompt_check.set_sensitive(mode in {"farm_cycle", "attack_loop"})
        self.skip_upgrade_check.set_sensitive(mode == "farm_cycle")

        if mode == "farm_cycle" and self.result_wait_spin.get_value() <= 10:
            self.result_wait_spin.set_value(185)
        elif mode == "attack_loop" and self.result_wait_spin.get_value() > 60:
            self.result_wait_spin.set_value(8)

    def _on_start_clicked(self, _button: Gtk.Button) -> None:
        if self.worker is not None:
            return
        try:
            commands, delays = self._build_commands()
        except ValueError as exc:
            self._append_log(f"{exc}\n")
            return

        self._set_running(True)
        self._append_log("\n")
        self.worker = CommandWorker(
            commands,
            cwd=PROJECT_DIR,
            delays=delays,
            emit=self._append_log_threadsafe,
            done=self._worker_done_threadsafe,
        )
        self.worker.start()

    def _on_stop_clicked(self, _button: Gtk.Button) -> None:
        if self.worker is not None:
            self.status_label.set_text("Stopping...")
            self.worker.stop()

    def _on_screenshot_clicked(self, _button: Gtk.Button) -> None:
        stamp = time.strftime("%Y%m%dT%H%M%S")
        out = f"screenshots/gui_{stamp}.png"
        command = self._base_command() + ["screenshot", "--profile", self._selected(self.profile_combo), "--out", out]
        self._add_common_subcommand_options(command)
        if self.dry_run_check.get_active():
            command.append("--dry-run")
        self._run_single_background(command)

    def _on_fov_clicked(self, _button: Gtk.Button) -> None:
        command = self._base_command() + [
            "zoom-out",
            "--profile",
            self._selected(self.profile_combo),
            "--steps",
            "8",
        ]
        self._add_common_subcommand_options(command)
        if self.dry_run_check.get_active():
            command.append("--dry-run")
        self._run_single_background(command)

    def _on_mirror_clicked(self, _button: Gtk.Button) -> None:
        launcher = Path("/home/carlo/.local/bin/clash-phone")
        if not launcher.exists():
            self._append_log(f"{launcher} does not exist\n")
            return
        env = os.environ.copy()
        selected_profile = self._selected(self.profile_combo).lower()
        if "ipad" in selected_profile or "1600x1200" in selected_profile:
            env["CLASH_PRESET"] = "ipad"
        subprocess.Popen(
            [str(launcher)],
            cwd=Path.home(),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        preset = f" ({env['CLASH_PRESET']} preset)" if env.get("CLASH_PRESET") else ""
        self._append_log(f"launched {launcher}{preset}\n")
        GLib.timeout_add(1200, self.place_over_clash)

    def _run_single_background(self, command: list[str]) -> None:
        if self.worker is not None:
            self._append_log("A command is already running.\n")
            return
        self._set_running(True)
        self.worker = CommandWorker(
            [command],
            cwd=PROJECT_DIR,
            delays=[],
            emit=self._append_log_threadsafe,
            done=self._worker_done_threadsafe,
        )
        self.worker.start()

    def _base_command(self) -> list[str]:
        command = [sys.executable, "-m", "clashbot"]
        if self.args.adb:
            command += ["--adb", self.args.adb]
        if self.args.serial:
            command += ["--serial", self.args.serial]
        return command

    def _add_common_subcommand_options(self, command: list[str]) -> None:
        if self.args.display:
            command += ["--display", self.args.display]

    def _build_commands(self) -> tuple[list[list[str]], list[float]]:
        mode = self.mode_combo.get_active_id() or "farm_cycle"
        profile = self._selected(self.profile_combo)
        routine = self._selected(self.routine_combo)
        state = self._selected(self.state_combo)
        cycles = int(self.cycles_spin.get_value())
        delay = float(self.delay_spin.get_value())
        result_wait = float(self.result_wait_spin.get_value())
        upgrade_every = int(self.upgrade_every_spin.get_value())
        upgrade_max = int(self.upgrade_max_spin.get_value())
        dry_run = self.dry_run_check.get_active()

        if not profile:
            raise ValueError("Choose a profile first.")

        base = self._base_command()

        if mode == "farm_cycle":
            command = base + [
                "farm-cycle",
                "--profile",
                profile,
                "--routines-dir",
                "routines",
                "--attack-routine",
                routine,
                "--cycles",
                str(cycles),
                "--delay",
                str(delay),
                "--result-wait",
                str(result_wait),
                "--upgrade-state",
                state,
                "--upgrade-every",
                str(upgrade_every),
                "--upgrade-max",
                str(upgrade_max),
            ]
            self._add_common_subcommand_options(command)
            if self.prompt_check.get_active():
                command.append("--prompt-result")
            if self.skip_upgrade_check.get_active():
                command.append("--skip-upgrade")
            if dry_run:
                command.append("--dry-run")
            return [command], []

        if mode == "attack_loop":
            command = base + [
                "attack",
                "--profile",
                profile,
                "--routines-dir",
                "routines",
                "--routine",
                routine,
                "--repeat",
                str(cycles),
                "--delay",
                str(delay),
                "--result-wait",
                str(result_wait),
            ]
            self._add_common_subcommand_options(command)
            if self.prompt_check.get_active():
                command.append("--prompt-result")
            if dry_run:
                command.append("--dry-run")
            return [command], []

        if mode == "upgrade_loop":
            command = base + [
                "upgrade",
                "--state",
                state,
                "--profile",
                profile,
                "--routines-dir",
                "routines",
                "--max",
                str(upgrade_max),
            ]
            self._add_common_subcommand_options(command)
            if dry_run:
                command.append("--dry-run")
            return [list(command) for _ in range(cycles)], [delay] * max(0, cycles - 1)

        if mode == "run_routine":
            command = base + [
                "run",
                "--profile",
                profile,
                "--routine",
                routine,
                "--repeat",
                str(cycles),
                "--delay",
                str(delay),
            ]
            self._add_common_subcommand_options(command)
            if dry_run:
                command.append("--dry-run")
            return [command], []

        if mode == "plan":
            command = base + ["plan", "--state", state, "--max", str(upgrade_max)]
            return [command], []

        raise ValueError(f"Unknown mode: {mode}")

    def _selected(self, combo: Gtk.ComboBoxText) -> str:
        text = combo.get_active_text()
        return text.strip() if text else ""

    def _set_running(self, running: bool) -> None:
        self.start_button.set_sensitive(not running)
        self.stop_button.set_sensitive(running)
        self.status_label.set_text("Running..." if running else "Idle")

    def _append_log_threadsafe(self, text: str) -> None:
        self.log_queue.put(text)

    def _append_log(self, text: str) -> None:
        buffer = self.log_view.get_buffer()
        end = buffer.get_end_iter()
        buffer.insert(end, text)
        mark = buffer.create_mark(None, buffer.get_end_iter(), False)
        self.log_view.scroll_mark_onscreen(mark)

    def _drain_log(self) -> bool:
        while True:
            try:
                text = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self._append_log(text)
        return True

    def _worker_done_threadsafe(self, code: int | None) -> None:
        GLib.idle_add(self._worker_done, code)

    def _worker_done(self, code: int | None) -> bool:
        self.worker = None
        self._set_running(False)
        if code is None:
            self.status_label.set_text("Stopped")
        elif code == 0:
            self.status_label.set_text("Done")
        else:
            self.status_label.set_text(f"Failed: exit {code}")
        return False

    def _on_destroy(self, _window: Gtk.Window) -> None:
        if self.worker is not None:
            self.worker.stop()
        Gtk.main_quit()

    def place_over_clash(self) -> bool:
        geometry = self._find_clash_geometry()
        if geometry is None:
            self._append_log("Clash window not found; leaving panel where it is.\n")
            return False
        x, y, width, _height = geometry
        panel_width, _panel_height = self.get_size()
        target_x = max(0, x + width - panel_width - 18)
        target_y = max(0, y + 56)
        self.move(target_x, target_y)
        self.present()
        return False

    def _find_clash_geometry(self) -> tuple[int, int, int, int] | None:
        try:
            Wnck.set_client_type(Wnck.ClientType.PAGER)
        except Exception:
            pass
        screen = Wnck.Screen.get_default()
        if screen is None:
            return None
        screen.force_update()
        title_token = (self.args.window_title or "Clash of Clans").lower()
        fallback: tuple[int, int, int, int] | None = None
        for window in screen.get_windows():
            title = (window.get_name() or "").lower()
            class_name = " ".join(
                part
                for part in (
                    window.get_class_group_name() or "",
                    window.get_class_instance_name() or "",
                )
                if part
            ).lower()
            if "scrcpy" in class_name or "scrcpy" in title:
                fallback = window.get_geometry()
            if title_token in title:
                return window.get_geometry()
        return fallback


def run(args: argparse.Namespace) -> int:
    window = ClashbotOverlay(args)
    window.show_all()
    Gtk.main()
    return 0
