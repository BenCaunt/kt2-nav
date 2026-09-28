#!/bin/zsh
set -eu
cd -- "$(dirname -- "$0")"
if ! command -v uv >/dev/null 2>&1; then
  export PATH="$PATH:$HOME/.local/bin:/opt/homebrew/bin"
fi
if ! command -v uv >/dev/null 2>&1; then
  print "Install uv first: https://docs.astral.sh/uv/getting-started/installation/"
  exit 1
fi
exec uv run --no-project --managed-python --python 3.12 --with 'aiohttp>=3.12,<4' python -m kt2_tracking --record "$@"
