#!/usr/bin/env bash
set -euo pipefail

sudo apt update && sudo apt install -y fish
echo "$(which fish)" | sudo tee -a /etc/shells
sudo chsh -s "$(which fish)" "$USER"
mkdir -p ~/.config/fish/functions
curl -fsSL https://raw.githubusercontent.com/ShawnZhong/scripts/refs/heads/main/fish/config.fish > ~/.config/fish/config.fish
curl -fsSL https://raw.githubusercontent.com/ShawnZhong/scripts/refs/heads/main/fish/fish_prompt.fish > ~/.config/fish/functions/fish_prompt.fish
fish -c "fish_add_path ~/.local/bin"
