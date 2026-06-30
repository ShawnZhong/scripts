sudo apt update && sudo apt install -y fish
echo $(which fish) | sudo tee -a /etc/shells
sudo chsh -s $(which fish) $USER
mkdir -p ~/.config/fish/functions
curl https://gist.githubusercontent.com/ShawnZhong/75f3a2c73d5a1375a51bae0bebee688a/raw/config.fish > ~/.config/fish/config.fish
curl https://gist.githubusercontent.com/ShawnZhong/75f3a2c73d5a1375a51bae0bebee688a/raw/fish_prompt.fish > ~/.config/fish/functions/fish_prompt.fish
fish -c "fish_add_path ~/.local/bin"
