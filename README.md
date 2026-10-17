Setup scripts for a fresh Ubuntu machine.

Setup fish, git, and Claude Code settings (no commit/PR attribution):
```sh
bash <(curl -fsSL https://raw.githubusercontent.com/ShawnZhong/scripts/refs/heads/main/setup.sh)
```

CloudLab repartition:
```sh
curl -fsSL https://raw.githubusercontent.com/ShawnZhong/scripts/refs/heads/main/repartition.py | sudo python3
```

Run an Ubuntu cloud image in a VM: vfkit on macOS, QEMU on Linux x86_64 (data lives in `./vm`, SSH in after boot):

```sh
./vm.py setup    # install deps, set up KVM, download image, build seed
./vm.py          # start, then SSH in
./vm.py start    # boot in the background; runs setup if needed
./vm.py ssh      # wait for the guest's sshd, then SSH in
./vm.py stop     # shut the VM down
./vm.py reset    # stop and wipe the VM (keeps the downloaded base image)
```

To `ssh ubuntu-vm` from anywhere, add `Include ~/Code/scripts/vm/*/ssh_config` at the top of `~/.ssh/config`.
