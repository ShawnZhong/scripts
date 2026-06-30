#!/usr/bin/env bash
set -euo pipefail

sudo apt update && sudo apt install -y fish
echo "$(which fish)" | sudo tee -a /etc/shells
sudo chsh -s "$(which fish)" "$USER"
base=https://raw.githubusercontent.com/ShawnZhong/scripts/refs/heads/main/fish
for f in config.fish functions/fish_prompt.fish; do
  mkdir -p ~/.config/fish/"$(dirname "$f")"
  curl -fsSL "$base/$f" > ~/.config/fish/"$f"
done
fish -c "fish_add_path ~/.local/bin"
