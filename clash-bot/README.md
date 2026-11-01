# Clash Local Bot

Local-only automation scaffold for a modded Clash-style APK. It drives the APK from the outside with ADB taps, swipes, screenshots, and JSON routines.

This is intentionally not an anti-cheat bypass, packet bot, or APK patcher. Use it only against your own local modded APK or a server you control.

## Quick Start

From this directory:

```bash
python3 -m clashbot devices
python3 -m clashbot screenshot --out screenshots/home.png
python3 -m clashbot plan --state state/village_state.example.json
python3 -m clashbot run --profile profiles/example_1080x1920.json --routine routines/attack_spread_example.json --dry-run
python3 -m clashbot upgrade --state state/village_state.example.json --profile profiles/example_1080x1920.json --dry-run
```

You can also use the local wrapper from any directory:

```bash
clashbot attack --profile profiles/clash_1600x900_display_auto.json
```

Remove `--dry-run` once the profile coordinates match your device or emulator.

## Current 1600x900 Clash Setup

Your local mirror is launched by:

```bash
/home/carlo/.local/bin/clash-phone
```

That launcher starts scrcpy with `--new-display=1600x900/240`, `--render-fit=letterbox`, `--max-fps=75`, and app package `com.supercell.clashofclans`. It opens as a normal `1440x810` window on the right-hand screen by default, while the Android virtual display remains 16:9 so the bot can see the full game edges.

There is also an experimental tablet-style/iPad FOV launcher:

```bash
/home/carlo/.local/bin/clash-ipad
```

That is a wrapper for `CLASH_PRESET=ipad /home/carlo/.local/bin/clash-phone`, which starts scrcpy with
`--new-display=1600x1200/240` and `--render-fit=stretched`. It is not the default bot setup. Use the matching profile only when you intentionally launch that view:

```bash
profiles/clash_ipad_1600x1200_display_auto.json
```

Use the calibrated profile:

```bash
profiles/clash_1600x900_display_auto.json
```

The Android display id changes on every scrcpy launch, so the active profile uses `"id": "auto"`. The bot detects the active `1600x900` Clash display before running a routine.

Open one match without deploying:

```bash
python3 -m clashbot run --profile profiles/clash_1600x900_display_auto.json --routine routines/clash_attack_open_match_1400x900.json
```

Run a calibrated full-send attack:

```bash
python3 -m clashbot run --profile profiles/clash_1600x900_display_auto.json --routine routines/clash_attack_full_send_1400x900.json
```

Run the improved learned-attack entry point:

```bash
python3 -m clashbot attack --profile profiles/clash_1600x900_display_auto.json
```

The default attack strategy is now `edrag_funnel`, backed by `routines/clash_attack_edrag_bottom_push_widescreen.json`.
It uses a cleaner bottom-side E-Dragon pattern for the 1600x900 widescreen view: heroes start a lower funnel, Balloons scout
traps, Electro Dragons deploy as one line behind them, then Rage and Freeze support the push through the core.

The bottom-push routine uses fixed calibrated deployment points instead of live perimeter adjustment. The perimeter
detector is still available for older routines, but the learned attack avoids it because the red boundary is not
visible reliably during the countdown.

The attack routine also checks for the troop bar before opening a match. If you are already on an opponent screen it
deploys from there; otherwise it opens Multiplayer, taps Find a Match, and waits only until the troop bar is visible.

After an attack, train the ranking with the observed result:

```bash
python3 -m clashbot record-result --stars 2 --destruction 71
python3 -m clashbot attack-stats
```

`record-result` updates the latest unscored attack by default. Use the numbered rows from `attack-stats` to target a
specific run:

```bash
python3 -m clashbot record-result --attack-index 14 --stars 2 --destruction 71 --loot-gold 100000
```

Run 5 attacks with a short pause between each:

```bash
python3 -m clashbot attack --profile profiles/clash_1600x900_display_auto.json --repeat 5 --delay 10
```

Run farm cycles and try the suggested upgrade flow after each completed attack:

```bash
python3 -m clashbot farm-cycle --profile profiles/clash_1600x900_display_auto.json --cycles 3
```

`farm-cycle` waits 185 seconds by default so the attack can finish, presses Back once to return home, then runs the
upgrade planner with `state/village_state.example.json`. Use `--skip-upgrade` to attack only. Add `--prompt-result`
if you are watching the run and want to enter stars, destruction, and loot after each attack.

Open the always-on-top GUI overlay for the Clash window:

```bash
python3 -m clashbot gui
```

The overlay defaults to the iPad/tablet profile. It can launch the mirror, snap itself over the scrcpy window, and run
farm cycles, attack loops, upgrade loops, single routines, screenshots, or upgrade plans without leaving the game window.

Run the first suggested upgrade flow:

```bash
python3 -m clashbot run --profile profiles/clash_1600x900_display_auto.json --routine routines/clash_upgrade_suggested_1400x900.json
```

Use `--dry-run` first whenever you edit anchors or routines.

## Calibration

1. Open the modded APK on the device or emulator.
2. Save a screenshot:

```bash
python3 -m clashbot screenshot --out screenshots/home.png
```

3. Open the screenshot and note the pixel coordinates for each button you need.
4. Convert each coordinate to normalized values:

```text
x = pixel_x / screenshot_width
y = pixel_y / screenshot_height
```

5. Edit `profiles/example_1080x1920.json` or create a new profile.

Normalized anchors make the same routine easier to reuse across similar screen sizes.

## Routines

Routines are JSON files under `routines/`. Supported steps:

```json
{ "tap": "anchor_name", "wait_after": 0.5 }
{ "tap": { "x": 0.5, "y": 0.8 } }
{ "swipe": { "from": "deploy_top_left", "to": "deploy_bottom_right", "duration_ms": 450 } }
{ "wait": 2.0 }
{ "keyevent": "BACK" }
{ "screenshot": "screenshots/checkpoint.png" }
{ "repeat": 3, "steps": [ { "tap": "deploy_top_left" } ] }
```

Use `--dry-run` first. It prints the exact ADB commands without touching the device.

## Upgrade Planner

`state/village_state.example.json` is a local model of your village. Edit resources, free builders, focus, weights, and the upgrades list.

Run:

```bash
python3 -m clashbot plan --state state/village_state.example.json --max 2
```

The planner ranks affordable upgrades by priority, category weights, focus tags, build time window, prerequisites, and resource pressure. Town Hall upgrades are gated by default: set `"town_hall_upgrade": true` or `"category": "town_hall"`, and the planner will only choose it when every non-Town-Hall upgrade in the state is marked `"maxed": true`, `"done": true`, or `"complete": true`.

To execute the selected upgrade routines:

```bash
python3 -m clashbot upgrade --state state/village_state.example.json --profile profiles/example_1080x1920.json --max 2
```

Each upgrade entry can set `"routine": "some_routine_name"`, which maps to `routines/some_routine_name.json`.

## Useful Commands

Launch by package name:

```bash
python3 -m clashbot launch com.example.clashmirror
```

Tap a raw coordinate:

```bash
python3 -m clashbot tap 540 1600
```

Run the suggested-upgrade macro:

```bash
python3 -m clashbot run --profile profiles/example_1080x1920.json --routine routines/upgrade_suggested_example.json
```

## Next Improvements

- Add your exact APK package name to a small launcher script.
- Make one profile per emulator resolution.
- Record separate attack routines for different army comps.
- Expand `village_state.json` with every building and hero upgrade.
