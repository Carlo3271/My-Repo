from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .adb import ADB
from .config import display_from_profile, load_json, screen_from_profile


X = ctypes.cdll.LoadLibrary("libX11.so.6")
XTST_PATH = ctypes.util.find_library("Xtst")
Xtst = ctypes.cdll.LoadLibrary(XTST_PATH) if XTST_PATH else None

Atom = ctypes.c_ulong
Bool = ctypes.c_int
Display = ctypes.c_void_p
Window = ctypes.c_ulong

AnyPropertyType = 0
ButtonPress = 4
ButtonPressMask = 1 << 2
AsyncPointer = 0
ReplayPointer = 2
GrabModeAsync = 1
LockMask = 1 << 1
Mod2Mask = 1 << 4
Mod4Mask = 1 << 6


class XButtonEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", Bool),
        ("display", Display),
        ("window", Window),
        ("root", Window),
        ("subwindow", Window),
        ("time", ctypes.c_ulong),
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("x_root", ctypes.c_int),
        ("y_root", ctypes.c_int),
        ("state", ctypes.c_uint),
        ("button", ctypes.c_uint),
        ("same_screen", Bool),
    ]


class XEvent(ctypes.Union):
    _fields_ = [
        ("type", ctypes.c_int),
        ("xbutton", XButtonEvent),
        ("pad", ctypes.c_long * 24),
    ]


class XWindowAttributes(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("width", ctypes.c_int),
        ("height", ctypes.c_int),
        ("border_width", ctypes.c_int),
        ("depth", ctypes.c_int),
        ("visual", ctypes.c_void_p),
        ("root", Window),
        ("class", ctypes.c_int),
        ("bit_gravity", ctypes.c_int),
        ("win_gravity", ctypes.c_int),
        ("backing_store", ctypes.c_int),
        ("backing_planes", ctypes.c_ulong),
        ("backing_pixel", ctypes.c_ulong),
        ("save_under", Bool),
        ("colormap", ctypes.c_ulong),
        ("map_installed", Bool),
        ("map_state", ctypes.c_int),
        ("all_event_masks", ctypes.c_long),
        ("your_event_mask", ctypes.c_long),
        ("do_not_propagate_mask", ctypes.c_long),
        ("override_redirect", Bool),
        ("screen", ctypes.c_void_p),
    ]


X.XOpenDisplay.argtypes = [ctypes.c_char_p]
X.XOpenDisplay.restype = Display
X.XDefaultRootWindow.argtypes = [Display]
X.XDefaultRootWindow.restype = Window
X.XInternAtom.argtypes = [Display, ctypes.c_char_p, Bool]
X.XInternAtom.restype = Atom
X.XKeysymToKeycode.argtypes = [Display, ctypes.c_ulong]
X.XKeysymToKeycode.restype = ctypes.c_uint
X.XGetWindowProperty.argtypes = [
    Display,
    Window,
    Atom,
    ctypes.c_long,
    ctypes.c_long,
    Bool,
    Atom,
    ctypes.POINTER(Atom),
    ctypes.POINTER(ctypes.c_int),
    ctypes.POINTER(ctypes.c_ulong),
    ctypes.POINTER(ctypes.c_ulong),
    ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
]
X.XGetWindowProperty.restype = ctypes.c_int
X.XGetWindowAttributes.argtypes = [Display, Window, ctypes.POINTER(XWindowAttributes)]
X.XGetWindowAttributes.restype = ctypes.c_int
X.XTranslateCoordinates.argtypes = [
    Display,
    Window,
    Window,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_int),
    ctypes.POINTER(ctypes.c_int),
    ctypes.POINTER(Window),
]
X.XTranslateCoordinates.restype = Bool
X.XFree.argtypes = [ctypes.c_void_p]
X.XFree.restype = ctypes.c_int
X.XGrabButton.argtypes = [
    Display,
    ctypes.c_uint,
    ctypes.c_uint,
    Window,
    Bool,
    ctypes.c_uint,
    ctypes.c_int,
    ctypes.c_int,
    Window,
    ctypes.c_ulong,
]
X.XGrabButton.restype = ctypes.c_int
X.XAllowEvents.argtypes = [Display, ctypes.c_int, ctypes.c_ulong]
X.XAllowEvents.restype = ctypes.c_int
X.XNextEvent.argtypes = [Display, ctypes.POINTER(XEvent)]
X.XNextEvent.restype = ctypes.c_int
X.XSync.argtypes = [Display, Bool]
X.XSync.restype = ctypes.c_int
X.XFlush.argtypes = [Display]
X.XFlush.restype = ctypes.c_int
X.XCloseDisplay.argtypes = [Display]
X.XCloseDisplay.restype = ctypes.c_int
ERROR_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int, Display, ctypes.c_void_p)
X.XSetErrorHandler.argtypes = [ERROR_HANDLER]
X.XSetErrorHandler.restype = ERROR_HANDLER
if Xtst is not None:
    Xtst.XTestFakeMotionEvent.argtypes = [Display, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
    Xtst.XTestFakeMotionEvent.restype = ctypes.c_int
    Xtst.XTestFakeButtonEvent.argtypes = [Display, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
    Xtst.XTestFakeButtonEvent.restype = ctypes.c_int
    Xtst.XTestFakeKeyEvent.argtypes = [Display, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
    Xtst.XTestFakeKeyEvent.restype = ctypes.c_int


def open_display() -> tuple[Display, Window]:
    display_name = os.environ.get("DISPLAY", ":0").encode()
    display = X.XOpenDisplay(display_name)
    if not display:
        raise SystemExit(f"cannot open display {display_name.decode()}")
    return display, X.XDefaultRootWindow(display)


def atom(display: Display, name: str) -> Atom:
    return X.XInternAtom(display, name.encode(), False)


def get_prop(display: Display, window: int, name: str, count: int = 4096) -> tuple[Any, int]:
    actual_type = Atom()
    actual_format = ctypes.c_int()
    nitems = ctypes.c_ulong()
    bytes_after = ctypes.c_ulong()
    prop = ctypes.POINTER(ctypes.c_ubyte)()
    status = X.XGetWindowProperty(
        display,
        Window(window),
        atom(display, name),
        0,
        count,
        False,
        AnyPropertyType,
        ctypes.byref(actual_type),
        ctypes.byref(actual_format),
        ctypes.byref(nitems),
        ctypes.byref(bytes_after),
        ctypes.byref(prop),
    )
    if status != 0 or not prop:
        return None, 0
    try:
        if actual_format.value == 8:
            return ctypes.string_at(prop, nitems.value), 8
        if actual_format.value == 32:
            arr = ctypes.cast(prop, ctypes.POINTER(ctypes.c_ulong))
            return [int(arr[i]) for i in range(nitems.value)], 32
        return None, actual_format.value
    finally:
        X.XFree(prop)


def text_prop(display: Display, window: int, *names: str) -> str:
    for name in names:
        value, fmt = get_prop(display, window, name)
        if value and fmt == 8:
            return value.replace(b"\x00", b" ").decode("utf-8", "replace").strip()
    return ""


def client_windows(display: Display, root: Window) -> list[int]:
    clients, fmt = get_prop(display, int(root), "_NET_CLIENT_LIST")
    return clients if clients and fmt == 32 else []


def class_prop(display: Display, window: int) -> str:
    value, fmt = get_prop(display, window, "WM_CLASS")
    if not value or fmt != 8:
        return ""
    return " ".join(part.decode("utf-8", "replace") for part in value.split(b"\x00") if part)


def match_windows(display: Display, root: Window, token: str) -> list[int]:
    token = token.lower()
    matches: list[int] = []
    for window in client_windows(display, root):
        haystack = " ".join(
            [
                text_prop(display, window, "_NET_WM_NAME", "WM_NAME"),
                class_prop(display, window),
            ]
        ).lower()
        if token in haystack or "scrcpy" in haystack:
            matches.append(window)
    return matches


def window_geometry(display: Display, root: Window, window: int) -> tuple[int, int, int, int] | None:
    attrs = XWindowAttributes()
    if not X.XGetWindowAttributes(display, Window(window), ctypes.byref(attrs)):
        return None
    x = ctypes.c_int()
    y = ctypes.c_int()
    child = Window()
    X.XTranslateCoordinates(
        display,
        Window(window),
        root,
        0,
        0,
        ctypes.byref(x),
        ctypes.byref(y),
        ctypes.byref(child),
    )
    return int(x.value), int(y.value), int(attrs.width), int(attrs.height)


def point_over_match(display: Display, root: Window, token: str, x: int, y: int) -> bool:
    return matched_geometry_at_point(display, root, token, x, y) is not None


def matched_geometry_at_point(
    display: Display,
    root: Window,
    token: str,
    x: int,
    y: int,
) -> tuple[int, int, int, int] | None:
    for window in match_windows(display, root, token):
        geometry = window_geometry(display, root, window)
        if geometry is None:
            continue
        wx, wy, width, height = geometry
        if wx <= x < wx + width and wy <= y < wy + height:
            return geometry
    return None


def window_matches(display: Display, window: int, token: str) -> bool:
    if not window:
        return False
    haystack = " ".join(
        [
            text_prop(display, window, "_NET_WM_NAME", "WM_NAME"),
            class_prop(display, window),
        ]
    ).lower()
    token = token.lower()
    return token in haystack or "scrcpy" in haystack


def grab_wheel(display: Display, window: int, errors: list[int]) -> set[int]:
    grabbed: set[int] = set()
    modifiers = (
        0,
        LockMask,
        Mod2Mask,
        LockMask | Mod2Mask,
        Mod4Mask,
        Mod4Mask | LockMask,
        Mod4Mask | Mod2Mask,
        Mod4Mask | LockMask | Mod2Mask,
    )
    for button in (4, 5):
        for modifier in modifiers:
            before = len(errors)
            X.XGrabButton(
                display,
                button,
                modifier,
                Window(window),
                False,
                ButtonPressMask,
                GrabModeAsync,
                GrabModeAsync,
                Window(0),
                0,
            )
            X.XSync(display, False)
            if len(errors) == before:
                grabbed.add(button)
    X.XSync(display, False)
    return grabbed


def resolve_display_id(args: argparse.Namespace, profile: dict[str, Any]) -> int | None:
    raw = args.display
    if raw is None:
        raw = display_from_profile(profile)
    if raw == "auto":
        package = str(profile.get("package", "com.supercell.clashofclans"))
        screen = screen_from_profile(profile)
        return ADB(adb_path=args.adb, serial=args.serial).detect_display_id(package, size=screen)
    return int(raw) if raw is not None else None


def stop_conflicting_helpers() -> None:
    own_pid = os.getpid()
    patterns = (
        "python3 -m clashbot wheel-zoom",
        "clash-wheel-zoom",
        "x11ctl desktop-scroll",
    )
    try:
        output = subprocess.run(
            ["pgrep", "-af", "|".join(patterns)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        ).stdout
    except OSError:
        return

    for line in output.splitlines():
        parts = line.strip().split(maxsplit=1)
        if not parts:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        if pid == own_pid:
            continue
        command = parts[1] if len(parts) > 1 else ""
        if command.startswith(("timeout ", "bash ", "/usr/bin/bash ")):
            continue
        if not any(pattern in command for pattern in patterns):
            continue
        try:
            os.kill(pid, 15)
        except ProcessLookupError:
            pass


class ZoomWorker:
    def __init__(self, duration_ms: int) -> None:
        self.duration_ms = duration_ms
        self.lock = threading.Lock()

    def zoom_out(self, geometry: tuple[int, int, int, int]) -> None:
        self._run("out", geometry)

    def zoom_in(self, geometry: tuple[int, int, int, int]) -> None:
        self._run("in", geometry)

    def _run(self, direction: str, geometry: tuple[int, int, int, int]) -> None:
        if not self.lock.acquire(blocking=False):
            return
        try:
            synthesize_scrcpy_pinch(geometry, direction, self.duration_ms)
        finally:
            self.lock.release()


def synthesize_scrcpy_pinch(geometry: tuple[int, int, int, int], direction: str, duration_ms: int) -> None:
    if Xtst is None:
        return

    display, _root = open_display()
    try:
        ctrl = X.XKeysymToKeycode(display, 0xFFE3)  # XK_Control_L
        x, y, width, height = geometry
        center_x = x + width // 2
        center_y = y + height // 2
        near_x = x + round(width * 0.56)
        far_x = x + round(width * 0.82)
        start_x, end_x = (far_x, near_x) if direction == "out" else (near_x, far_x)

        Xtst.XTestFakeMotionEvent(display, -1, start_x, center_y, 0)
        X.XFlush(display)
        time.sleep(0.025)

        Xtst.XTestFakeKeyEvent(display, ctrl, 1, 0)
        Xtst.XTestFakeButtonEvent(display, 1, 1, 0)
        X.XFlush(display)
        time.sleep(0.025)

        steps = 8
        sleep = max(0.004, duration_ms / 1000 / steps)
        for index in range(1, steps + 1):
            px = round(start_x + (end_x - start_x) * index / steps)
            Xtst.XTestFakeMotionEvent(display, -1, px, center_y, 0)
            X.XFlush(display)
            time.sleep(sleep)

        Xtst.XTestFakeButtonEvent(display, 1, 0, 0)
        Xtst.XTestFakeKeyEvent(display, ctrl, 0, 0)
        X.XFlush(display)
        time.sleep(0.025)
        Xtst.XTestFakeMotionEvent(display, -1, center_x, center_y, 0)
        X.XFlush(display)
    finally:
        X.XCloseDisplay(display)


def run(args: argparse.Namespace) -> int:
    if args.replace:
        stop_conflicting_helpers()
        time.sleep(0.15)

    profile = load_json(args.profile)
    screen = screen_from_profile(profile)
    if screen is None:
        raise ValueError(f"profile {args.profile!r} must define screen width and height")

    display_id = resolve_display_id(args, profile)
    zoom = ZoomWorker(args.duration_ms)

    display, root = open_display()
    grabbed: set[int] = set()
    errors: list[int] = []

    @ERROR_HANDLER
    def on_error(_display: Display, _error: ctypes.c_void_p) -> int:
        errors.append(1)
        return 0

    try:
        X.XSetErrorHandler(on_error)
        deadline = time.monotonic() + args.timeout
        target_found = False
        while not target_found:
            target_found = bool(match_windows(display, root, args.window_title))
            if target_found or time.monotonic() >= deadline:
                break
            time.sleep(0.25)

        if not target_found:
            raise SystemExit(f"no window matching {args.window_title!r} or scrcpy was found")

        grabbed_buttons = grab_wheel(display, int(root), errors)
        if not {4, 5}.issubset(grabbed_buttons):
            missing = ", ".join(str(button) for button in sorted({4, 5} - grabbed_buttons))
            raise SystemExit(f"could not grab wheel button(s): {missing}")

        print(
            "wheel zoom active: scroll down zooms out, scroll up zooms in "
            f"(display {display_id if display_id is not None else 'default'})",
            flush=True,
        )

        event = XEvent()
        while True:
            X.XNextEvent(display, ctypes.byref(event))
            if event.type != ButtonPress:
                continue
            button = int(event.xbutton.button)
            geometry = matched_geometry_at_point(
                display,
                root,
                args.window_title,
                int(event.xbutton.x_root),
                int(event.xbutton.y_root),
            )
            if geometry is None:
                X.XAllowEvents(display, ReplayPointer, event.xbutton.time)
                X.XFlush(display)
                continue

            X.XAllowEvents(display, AsyncPointer, event.xbutton.time)
            X.XFlush(display)
            if button == 5:
                print("wheel down -> zoom out", flush=True)
                threading.Thread(target=zoom.zoom_out, args=(geometry,), daemon=True).start()
            elif button == 4:
                print("wheel up -> zoom in", flush=True)
                threading.Thread(target=zoom.zoom_in, args=(geometry,), daemon=True).start()
            else:
                X.XAllowEvents(display, ReplayPointer, event.xbutton.time)
            X.XFlush(display)
    finally:
        X.XCloseDisplay(display)


def launch_detached(args: argparse.Namespace) -> int:
    project_dir = Path(__file__).resolve().parent.parent
    command = [
        sys.executable,
        "-m",
        "clashbot",
        "wheel-zoom",
        "--profile",
        args.profile,
        "--window-title",
        args.window_title,
        "--duration-ms",
        str(args.duration_ms),
    ]
    if args.display:
        command += ["--display", args.display]
    if args.adb:
        command = [command[0], "-m", "clashbot", "--adb", args.adb, *command[3:]]
    if args.serial:
        command = [command[0], "-m", "clashbot", "--serial", args.serial, *command[3:]]
    subprocess.Popen(
        command,
        cwd=project_dir,
        stdout=open("/tmp/clashbot-wheel-zoom.log", "a", encoding="utf-8"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    print("started wheel zoom helper; log: /tmp/clashbot-wheel-zoom.log")
    return 0
