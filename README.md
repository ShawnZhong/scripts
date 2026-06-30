Setup scripts for a fresh Ubuntu machine.

```sh
# Setup fish shell
curl -fsSL https://raw.githubusercontent.com/ShawnZhong/scripts/refs/heads/main/fish.sh | bash

# Setup git
curl -fsSL https://raw.githubusercontent.com/ShawnZhong/scripts/refs/heads/main/git.sh | bash

# Setup Claude Code
curl -fsSL https://raw.githubusercontent.com/ShawnZhong/scripts/refs/heads/main/claude.sh | bash

# Extend the root partition to fill the disk (CloudLab)
curl -fsSL https://raw.githubusercontent.com/ShawnZhong/scripts/refs/heads/main/cloudlab.py | sudo python3
```
