#!/usr/bin/env bash
set -euo pipefail

if ! command -v fish > /dev/null; then
  sudo apt update && sudo apt install -y fish
fi

fish_path="$(command -v fish)"
if ! grep -qxF "$fish_path" /etc/shells; then
  echo "$fish_path" | sudo tee -a /etc/shells
fi

sudo chsh -s "$fish_path" "$USER"
base=https://raw.githubusercontent.com/ShawnZhong/scripts/refs/heads/main/fish
for f in config.fish functions/fish_prompt.fish; do
  mkdir -p ~/.config/fish/"$(dirname "$f")"
  curl -fsSL "$base/$f" > ~/.config/fish/"$f"
done

mkdir -p ~/.local/bin
fish -c "fish_add_path ~/.local/bin"

exec fish < /dev/tty
