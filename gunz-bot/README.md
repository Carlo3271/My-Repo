# GunZ K-Style Bot

Private-room bot scripts for Freestyle GunZ/GunZ: The Duel footage and timing experiments.

This project does not bypass anti-cheat, read process memory, or play public matches. It sends normal keyboard and mouse input to the focused game window. Use it in private rooms, training rooms, or local testing only.

## What It Does

- Runs K-style input routines: butterfly, slash-shot, reload-shot, half-step, wall-cancel.
- Runs a video-friendly demo sequence across several routines.
- Learns better timings with a human-scored loop: the bot tries a timing, you score it from 0 to 5, and it saves the best profile.
- Provides a dry-run mode so you can inspect inputs before the bot touches the game.

## Requirements

- Linux/X11 session.
- Python 3.
- `xdotool` for real input control.

Install `xdotool` on Arch-based systems:

```bash
cd ~/gunz_kstyle_bot
scripts/install_deps_arch.sh
```

## Quick Test

Dry-run the bot without sending input:

```bash
cd ~/gunz_kstyle_bot
scripts/run_bot.sh check --dry-run
scripts/run_bot.sh list
scripts/run_bot.sh run butterfly --cycles 2 --dry-run --countdown 0
```

## Run In GunZ

1. Open GunZ and enter a private room or training room.
2. Stand somewhere safe.
3. Run a routine:

```bash
cd ~/gunz_kstyle_bot
scripts/run_bot.sh run butterfly --cycles 10
```

Run a recording-friendly demo pass:

```bash
cd ~/gunz_kstyle_bot
scripts/run_demo_take.sh
```

If the window name does not match, pass a custom search pattern:

```bash
scripts/run_bot.sh run butterfly --window-name "Freestyle" --cycles 10
```

## Learning Mode

Learning mode tunes the timing values. After every attempt, look at the game and score how clean it was from 0 to 5.

```bash
cd ~/gunz_kstyle_bot
scripts/run_bot.sh learn butterfly --trials 25 --cycles 3
```

Use the learned profile later:

```bash
scripts/run_bot.sh run butterfly --profile profiles/butterfly.json --cycles 12
```

## Safety

- Press `Ctrl+C` in the terminal to stop.
- If a key gets stuck, run:

```bash
scripts/run_bot.sh release
```

## Tuning

Edit `config/default.json` if your GunZ keybinds differ. The defaults assume:

- WASD movement.
- Space jump.
- Shift block.
- 1 sword.
- 2 and 3 guns.
- R reload.
- Left mouse attack.

The default timing values are starting points. GunZ clients, Wine, FPS, keyboard repeat behavior, and latency can all change what feels clean.
