#!/bin/zsh
set -eu
cd "${0:A:h}"
export PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/Library/Android/sdk/platform-tools:$PWD/android/.tools/sdk/platform-tools:$PATH"
printf 'Pairing code shown in KT2 Pose on Android: '
read -r token
if command -v uv >/dev/null 2>&1; then
  uv run --no-project --managed-python --python 3.12 --with 'aiohttp>=3.12,<4' python -m kt2_tracking --android --token "$token" --record
else
  python3 -m kt2_tracking --android --token "$token" --record
fi
