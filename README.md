Setup scripts for a fresh Ubuntu machine.

```sh
# Setup fish shell
bash <(curl -fsSL https://raw.githubusercontent.com/ShawnZhong/scripts/refs/heads/main/fish.sh)

# Setup git
curl -fsSL https://raw.githubusercontent.com/ShawnZhong/scripts/refs/heads/main/git.sh | bash

# Setup Claude Code
curl -fsSL https://raw.githubusercontent.com/ShawnZhong/scripts/refs/heads/main/claude.sh | bash
```

CloudLab repartition:
```sh
curl -fsSL https://raw.githubusercontent.com/ShawnZhong/scripts/refs/heads/main/repartition.py | sudo python3
```

Run an Ubuntu cloud image in QEMU (data lives in `./vm`, SSH in after boot):

```sh
./vm.py setup    # install deps, set up KVM, download image, build seed
./vm.py start    # boot (daemonized) and SSH in; runs setup if needed
./vm.py stop     # shut the VM down
./vm.py restart  # stop, then start
./vm.py reset    # wipe disk + seed (keeps the downloaded base image)
```
