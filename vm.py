#!/usr/bin/env python3

import argparse
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

CPUS = os.cpu_count()
MEM = 32 * 1024  # MB
DISK = "64G"
USER = "ubuntu"
HOSTNAME = "ubuntu-vm"

# macOS runs the VM under vfkit (Virtualization.framework), Linux under QEMU.
MACOS = platform.system() == "Darwin"

HOST = platform.machine()
ARCH = {"x86_64": "amd64", "arm64": "arm64"}.get(HOST) or sys.exit(
    f"Unsupported host architecture: {HOST}"
)

IMG_URL = f"https://cloud-images.ubuntu.com/minimal/releases/noble/release/ubuntu-24.04-minimal-cloudimg-{ARCH}.img"

VM_DIR = Path("vm").resolve()
BASE = VM_DIR / Path(IMG_URL).name
DISK_IMG = VM_DIR / "disk.raw"
SEED = VM_DIR / "seed.img"  # cloud-init NoCloud ISO, built from SEED_DIR
SEED_DIR = VM_DIR / "seed"
PIDFILE = VM_DIR / "vm.pid"
CONSOLE = VM_DIR / "console.log"  # guest serial console
VM_LOG = VM_DIR / "vm.log"  # the hypervisor's own output
SSH_CONFIG = VM_DIR / "ssh_config"
EFI_VARS = VM_DIR / "efi-vars"  # vfkit only: its EFI boot requires a store

# vfkit only: vmnet's default NAT subnet (the host is .1) and the static IP the
# guest takes in it, so the host can reach it without asking DHCP.
SUBNET = "192.168.64"
GUEST_IP = f"{SUBNET}.200"
# QEMU only: the localhost port its user-mode networking forwards to sshd.
SSH_PORT = "2200"

SSH_DIR = Path.home() / ".ssh"


def echo(cmd):
    """Print `cmd` shell-style and return it as strings, ready to run."""
    cmd = [str(c) for c in cmd]
    print("+", *cmd, flush=True)
    return cmd


def system(*cmd, check=True):
    subprocess.run(echo(cmd), check=check)


def alive(pid):
    """True if the process exists (portable replacement for /proc/<pid>)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def vm_pid():
    """The live VM process's PID, or None. A stale pidfile reads as None and
    is overwritten on the next start, so it never needs deleting."""
    try:
        pid = int(PIDFILE.read_text())
    except (FileNotFoundError, ValueError):
        return None
    return pid if alive(pid) else None


def spawn(cmd):
    """Run the hypervisor detached in its own session so it outlives this
    script, logging to VM_LOG and recording its PID in PIDFILE."""
    with VM_LOG.open("w") as log:
        proc = subprocess.Popen(
            echo(cmd),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    PIDFILE.write_text(str(proc.pid))
    # Bad arguments or a failed VM start make the hypervisor exit right away.
    time.sleep(1)
    if proc.poll() is not None:
        sys.exit(f"VM exited with status {proc.returncode} (see {VM_LOG})")


def pubkey():
    """Return the path to an SSH public key, generating one if none exists."""
    for name in ("id_ed25519", "id_rsa"):
        pub = SSH_DIR / f"{name}.pub"
        if pub.exists():
            return pub
    key = SSH_DIR / "id_ed25519"
    system("ssh-keygen", "-t", "ed25519", "-N", "", "-C", "vm.py", "-f", key)
    return key.with_suffix(".pub")


# The host commands needed to run a VM, mapped to the package providing each:
# Homebrew formulae on macOS, apt packages on Linux.
if MACOS:
    DEPS = {"vfkit": "vfkit", "qemu-img": "qemu", "xorriso": "xorriso"}
else:
    DEPS = {
        "qemu-system-x86_64": "qemu-system-x86",
        "qemu-img": "qemu-utils",
        "xorriso": "xorriso",
    }


def setup_deps():
    """Install any missing host packages needed to run the VM."""
    missing = [pkg for cmd, pkg in DEPS.items() if not shutil.which(cmd)]
    if not missing:
        return
    if MACOS:
        system("brew", "install", *missing)
    else:
        system("sudo", "apt-get", "update")
        system("sudo", "apt-get", "install", "-y", *missing)


def setup_kvm():
    """Relax /dev/kvm (root:kvm 0660) so this user can use KVM without root.
    Resets on reboot, but runs on every start, so it self-heals. vfkit on
    macOS needs no device permission."""
    if MACOS:
        return
    KVM = Path("/dev/kvm")
    if KVM.exists() and not os.access(KVM, os.R_OK | os.W_OK):
        system("sudo", "chmod", "666", KVM)
    if not os.access(KVM, os.R_OK | os.W_OK):
        print("/dev/kvm unavailable; using slow emulation.")


def setup_disk():
    """Download the cloud image and expand it into this VM's disk. Raw is the
    one format both QEMU and vfkit read; the file is sparse, so space is only
    used as the guest writes."""
    if not BASE.exists():
        system("curl", "-fL", "-o", BASE, IMG_URL)

    if not DISK_IMG.exists():
        system("qemu-img", "convert", "-O", "raw", BASE, DISK_IMG)
        system("qemu-img", "resize", "-f", "raw", DISK_IMG, DISK)


def setup_seed():
    """Build the cloud-init NoCloud seed ISO carrying the host's SSH key."""
    if SEED.exists():
        return
    # Written as JSON, which YAML parsers (and so cloud-init) accept as is.
    if MACOS:
        nic = {
            "addresses": [f"{GUEST_IP}/24"],
            "routes": [{"to": "default", "via": f"{SUBNET}.1"}],
            "nameservers": {"addresses": [f"{SUBNET}.1"]},
        }
    else:
        nic = {"dhcp4": True}
    files = {
        # USER is the image's default user, which already has sudo and bash.
        "user-data": "#cloud-config\n"
        + json.dumps({"ssh_authorized_keys": [pubkey().read_text().strip()]}),
        "meta-data": json.dumps({"instance-id": HOSTNAME, "local-hostname": HOSTNAME}),
        # Match the NIC by name: cloud-init's default config pins the first
        # boot's MAC, and vfkit picks a new random MAC on every start.
        "network-config": json.dumps(
            {"version": 2, "ethernets": {"nic": {"match": {"name": "en*"}, **nic}}}
        ),
    }
    SEED_DIR.mkdir(exist_ok=True)
    for name, text in files.items():
        (SEED_DIR / name).write_text(text)
    # The NoCloud datasource requires the volume label to be "cidata".
    system(
        "xorriso",
        "-as",
        "genisoimage",
        "-output",
        SEED,
        "-volid",
        "cidata",
        "-joliet",
        "-rock",
        SEED_DIR,
    )


def setup_ssh_config():
    """Write an ssh config for the guest, which `ssh` uses and which also
    works by hand (`ssh -F vm/ssh_config ubuntu-vm`) or via an Include in
    ~/.ssh/config. Host keys aren't checked: each reset makes new ones."""
    host, port = (GUEST_IP, 22) if MACOS else ("localhost", SSH_PORT)
    SSH_CONFIG.write_text(
        f"Host {HOSTNAME}\n"
        f"  HostName {host}\n"
        f"  Port {port}\n"
        f"  User {USER}\n"
        "  StrictHostKeyChecking no\n"
        "  UserKnownHostsFile /dev/null\n"
        "  LogLevel ERROR\n"
    )


def setup():
    """Run every setup step: deps, KVM, disk, seed, and ssh config."""
    VM_DIR.mkdir(exist_ok=True)
    setup_deps()
    setup_kvm()
    setup_disk()
    setup_seed()
    setup_ssh_config()


def qemu_cmd():
    """QEMU with KVM (if usable) and user-mode networking, which forwards
    localhost:SSH_PORT to the guest's sshd."""
    return [
        "qemu-system-x86_64",
        "-machine",
        "type=q35,accel=kvm:tcg",
        "-cpu",
        "max",
        "-smp",
        CPUS,
        "-m",
        MEM,
        "-display",
        "none",
        "-serial",
        f"file:{CONSOLE}",
        "-drive",
        f"if=virtio,format=raw,file={DISK_IMG}",
        "-drive",
        f"if=virtio,format=raw,file={SEED}",
        "-device",
        "virtio-net-pci,netdev=net0",
        "-netdev",
        f"user,id=net0,hostfwd=tcp:127.0.0.1:{SSH_PORT}-:22",
    ]


def vfkit_cmd():
    """vfkit with vmnet NAT networking; the guest sits at GUEST_IP."""
    return [
        "vfkit",
        "--cpus",
        CPUS,
        "--memory",
        MEM,
        "--bootloader",
        f"efi,variable-store={EFI_VARS},create",
        "--device",
        f"virtio-blk,path={DISK_IMG}",
        "--device",
        f"virtio-blk,path={SEED}",
        "--device",
        "virtio-net,nat",
        "--device",
        f"virtio-serial,logFilePath={CONSOLE}",
    ]


def start():
    if pid := vm_pid():
        print(f"VM already running (pid {pid})")
    else:
        setup()
        spawn(vfkit_cmd() if MACOS else qemu_cmd())


def stop():
    """SIGTERM the VM (both hypervisors exit at once, pulling the plug) and
    wait for it to go."""
    pid = vm_pid()
    if pid is None:
        print("VM not running")
        return
    os.kill(pid, signal.SIGTERM)
    while alive(pid):
        time.sleep(0.1)
    print("VM stopped")


def reset():
    """Stop the VM and delete everything in VM_DIR but the downloaded base
    image; the next start sets the VM up afresh."""
    stop()
    for f in VM_DIR.glob("*"):
        if f.is_dir():
            shutil.rmtree(f)
        elif f != BASE:
            f.unlink()


def ssh():
    """Open a shell in the guest, retrying the connection while it boots."""
    # check=False: exiting the shell with a nonzero status is normal, not an error.
    system(
        "ssh",
        "-F",
        SSH_CONFIG,
        "-o",
        "ConnectionAttempts=120",
        "-o",
        "ConnectTimeout=2",
        HOSTNAME,
        check=False,
    )


def main():
    cmds = {f.__name__: f for f in (setup, start, ssh, stop, reset)}
    parser = argparse.ArgumentParser(
        description="Run an Ubuntu cloud image in a VM (vfkit on macOS, QEMU on Linux)."
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=cmds,
        help="subcommand to run (default: start, then ssh)",
    )
    command = parser.parse_args().command
    if command is None:
        start()
        ssh()
    else:
        cmds[command]()


if __name__ == "__main__":
    main()
