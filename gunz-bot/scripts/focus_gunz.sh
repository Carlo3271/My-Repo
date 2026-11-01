#!/usr/bin/env bash
set -euo pipefail

pattern="${1:-GunZ|FGunZ|Freestyle}"

if ! command -v xdotool >/dev/null 2>&1; then
  echo "xdotool is required. Run scripts/install_deps_arch.sh first." >&2
  exit 1
fi

window_id="$(xdotool search --onlyvisible --name "$pattern" 2>/dev/null | tail -n 1 || true)"
if [[ -z "${window_id}" ]]; then
  echo "No visible GunZ window matched: ${pattern}" >&2
  exit 1
fi

xdotool windowactivate --sync "$window_id"
echo "Focused GunZ window: ${window_id}"
