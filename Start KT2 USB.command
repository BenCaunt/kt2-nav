#!/bin/zsh
set -eu
cd -- "$(dirname -- "$0")"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
if ! command -v iproxy >/dev/null; then
  echo "Install the USB bridge first: brew install libusbmuxd"
  exit 1
fi
if [[ $# == 0 ]]; then
  read -r 'kt2_code?Enter the USB pairing code shown in KT2 Pose: '
  exec uv run --no-project --managed-python --python 3.12 --with 'aiohttp>=3.12,<4' \
    python -m kt2_tracking --usb --token "$kt2_code" --record
else
  exec uv run --no-project --managed-python --python 3.12 --with 'aiohttp>=3.12,<4' \
    python -m kt2_tracking --usb --record "$@"
fi
