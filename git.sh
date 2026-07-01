#!/usr/bin/env bash
set -euo pipefail

if ! command -v git > /dev/null; then
  sudo apt update && sudo apt install -y git nano
fi

git config --global user.name "ShawnZhong"
git config --global user.email "github@shawnzhong.com"
git config --global fetch.prune true
git config --global core.editor "nano"
git config --global pull.ff only
git config --global push.autoSetupRemote true
