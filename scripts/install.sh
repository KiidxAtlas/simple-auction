#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${1:-https://github.com/KiidxAtlas/simple-auction.git}"
APP_NAME="simple-auction"

if command -v pipx >/dev/null 2>&1; then
  pipx install "git+${REPO_URL}" --force
  echo "Installed with pipx. Run: ${APP_NAME}"
  exit 0
fi

python3 -m pip install --user --upgrade "git+${REPO_URL}"
echo "Installed with pip --user. Ensure your user bin is on PATH, then run: ${APP_NAME}"
