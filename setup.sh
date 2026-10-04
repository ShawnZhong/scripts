#!/usr/bin/env bash
set -euo pipefail

sudo apt update && sudo apt install -y fish git nano

# git
git config --global user.name "ShawnZhong"
git config --global user.email "github@shawnzhong.com"
git config --global fetch.prune true
git config --global core.editor "nano"
git config --global core.mergeoptions "--no-edit"
git config --global rebase.autoStash true
git config --global push.autoSetupRemote true

# Claude Code: no attribution in commits / PRs
mkdir -p ~/.claude
echo '{"attribution": {"commit": "", "pr": ""}}' > ~/.claude/settings.json

# fish
sudo chsh -s "$(command -v fish)" "$USER"
base=https://raw.githubusercontent.com/ShawnZhong/scripts/refs/heads/main/fish
curl -fsSL --create-dirs \
  -o ~/.config/fish/config.fish "$base/config.fish" \
  -o ~/.config/fish/functions/fish_prompt.fish "$base/functions/fish_prompt.fish"

mkdir -p ~/.local/bin
fish -c "fish_add_path ~/.local/bin"

exec fish < /dev/tty
