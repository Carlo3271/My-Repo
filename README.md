# Portfolio Showcase — Automation & Systems Projects

Two independent Python projects demonstrating systems thinking, clean architecture, and practical automation.

---

## 1. Clash Local Bot (`clash-bot/`)

**Local-only automation scaffold for a modded Clash-style APK.** Drives the game via ADB (taps, swipes, screenshots) using JSON-defined routines and normalized screen coordinates.

**Highlights:**
- **Plugin-style CLI** (`python3 -m clashbot <subcommand>`) — devices, screenshot, tap, run, plan, upgrade, attack, farm-cycle, gui, wheel-zoom
- **Normalized anchor profiles** — same routines work across resolutions (1600×900, 1080×1920, iPad 1600×1200)
- **Upgrade planner** — ranks affordable upgrades by priority, build time, prerequisites, resource pressure; Town Hall gated until everything else maxed
- **Learning loop** — records attack results (stars, destruction, loot), scores strategies, re-ranks for next run
- **Dry-run mode** — prints exact ADB commands without touching the device
- **Always-on-top GUI overlay** (Tkinter) — launch mirror, snap over scrcpy, run cycles without leaving game window

**Stack:** Python 3, ADB, `xdotool`/`scrcpy` for display, Tkinter GUI, JSON config

---

## 2. GunZ K-Style Bot (`gunz-bot/`)

**Private-room input bot for Freestyle GunZ / GunZ: The Duel.** Sends synthetic keyboard/mouse input (via `xdotool`) to the focused game window. No memory reading, no anti-cheat interaction.

**Highlights:**
- **Technique library** — butterfly, slash-shot, reload-shot, half-step, wall-cancel, spar
- **Human-in-the-loop learning** — bot tries a timing, you score 0–5, saves best profile
- **Demo sequence** — video-friendly chained routines
- **Dry-run & release safety** — inspect inputs before sending; `release` command unsticks keys
- **Config-driven keybinds** — WASD, space, shift, 1/2/3, R, LMB defaults; fully customizable

**Stack:** Python 3, `xdotool` (X11), JSON config/profiles

---

## What These Demonstrate

| Skill | Clash Bot | GunZ Bot |
|-------|-----------|----------|
| Clean CLI design (argparse, subcommands) | ✓ | ✓ |
| Configuration-driven behavior (JSON profiles) | ✓ | ✓ |
| Coordinate normalization / resolution independence | ✓ | — |
| Planning / optimization algorithm | Upgrade planner | Timing learner |
| State persistence & learning loop | Attack learning | Technique learning |
| Safety-first automation (dry-run, release) | ✓ | ✓ |
| GUI overlay (Tkinter) | ✓ | — |
| Real-time input synthesis (ADB / xdotool) | ✓ | ✓ |
| Modular, testable package structure | ✓ | ✓ |

---

## Quick Start

```bash
# Clash Bot
cd clash-bot
python3 -m clashbot devices
python3 -m clashbot screenshot --out screenshots/home.png
python3 -m clashbot plan --state state/village_state.example.json --max 2

# GunZ Bot
cd gunz-bot
scripts/install_deps_arch.sh   # installs xdotool
python3 -m gunz_bot check --dry-run
python3 -m gunz_bot list
python3 -m gunz_bot run butterfly --cycles 2 --dry-run
```

---

## License

MIT — use freely for learning, portfolio, or private-room experimentation.