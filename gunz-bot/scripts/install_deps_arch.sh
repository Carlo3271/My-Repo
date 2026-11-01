#!/usr/bin/env bash
set -euo pipefail

if command -v xdotool >/dev/null 2>&1; then
  echo "xdotool is already installed."
  exit 0
fi

if command -v pacman >/dev/null 2>&1; then
  sudo pacman -S --needed xdotool
  exit 0
fi

echo "Install xdotool with your distro package manager, then rerun scripts/run_bot.sh check." >&2
exit 1
