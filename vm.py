#!/usr/bin/env python3

import argparse
import json
import os
import platform
import shutil
import signal
import socket
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

IMG_URL = f"https://cloud-images.ubuntu.com/minimal/releases/resolute/release/ubuntu-26.04-minimal-cloudimg-{ARCH}.img"

VM_DIR = Path("vm").resolve()
BASE = VM_DIR / Path(IMG_URL).name  # shared base image, kept by reset

# This VM's files, all deleted by reset.
INSTANCE = VM_DIR / HOSTNAME
DISK_IMG = INSTANCE / "disk.raw"
EFI_VARS = INSTANCE / "efi-vars"  # vfkit only; required for EFI boot
SEED_DIR = INSTANCE / "seed"  # cloud-init config
SEED = INSTANCE / "seed.img"  # ...packed into the ISO cloud-init reads
SSH_KEY = INSTANCE / "id_ed25519"  # this VM's own login key
SSH_CONFIG = INSTANCE / "ssh_config"

# Per-boot files, overwritten on each start.
RUN_DIR = INSTANCE / "run"
PIDFILE = RUN_DIR / "vm.pid"
CONSOLE = RUN_DIR / "console.log"  # guest serial output
VM_LOG = RUN_DIR / "vm.log"  # hypervisor output

# vfkit only: the guest's static IP on vmnet's default NAT subnet (host is .1).
SUBNET = "192.168.64"
GUEST_IP = f"{SUBNET}.200"
# The guest's sshd as the host sees it; QEMU forwards a localhost port to it.
SSH_HOST, SSH_PORT = (GUEST_IP, 22) if MACOS else ("localhost", 2200)


def echo(cmd):
    """Print `cmd` and return it as strings, ready to run."""
    cmd = [str(c) for c in cmd]
    print("+", *cmd, flush=True)
    return cmd


def system(*cmd, check=True):
    subprocess.run(echo(cmd), check=check)


def alive(pid):
    """True if the process exists."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def vm_pid():
    """The running VM's PID, or None (a stale pidfile counts as None)."""
    try:
        pid = int(PIDFILE.read_text())
    except (FileNotFoundError, ValueError):
        return None
    return pid if alive(pid) else None


def spawn(cmd):
    """Start the hypervisor in the background, logging to VM_LOG."""
    with VM_LOG.open("w") as log:
        proc = subprocess.Popen(
            echo(cmd),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    PIDFILE.write_text(str(proc.pid))
    # A bad config makes the hypervisor exit at once.
    time.sleep(1)
    if proc.poll() is not None:
        sys.exit(f"VM exited with status {proc.returncode} (see {VM_LOG})")


# Host commands needed, mapped to the Homebrew/apt package providing each.
if MACOS:
    DEPS = {"vfkit": "vfkit", "qemu-img": "qemu", "xorriso": "xorriso"}
else:
    DEPS = {
        "qemu-system-x86_64": "qemu-system-x86",
        "qemu-img": "qemu-utils",
        "xorriso": "xorriso",
    }


def setup_deps():
    """Install missing host packages."""
    missing = [pkg for cmd, pkg in DEPS.items() if not shutil.which(cmd)]
    if not missing:
        return
    if MACOS:
        system("brew", "install", *missing)
    else:
        system("sudo", "apt-get", "update")
        system("sudo", "apt-get", "install", "-y", *missing)


def setup_kvm():
    """Let this user open /dev/kvm. Reboots undo it, so it runs every start."""
    if MACOS:
        return
    KVM = Path("/dev/kvm")
    if KVM.exists() and not os.access(KVM, os.R_OK | os.W_OK):
        system("sudo", "chmod", "666", KVM)
    if not os.access(KVM, os.R_OK | os.W_OK):
        print("/dev/kvm unavailable; using slow emulation.")


def setup_disk():
    """Download the cloud image and make the VM's disk from it: raw, which
    both hypervisors read, and sparse, so it grows only as the guest writes."""
    if not BASE.exists():
        system("curl", "-fL", "-o", BASE, IMG_URL)

    if not DISK_IMG.exists():
        system("qemu-img", "convert", "-O", "raw", BASE, DISK_IMG)
        system("qemu-img", "resize", "-f", "raw", DISK_IMG, DISK)


def setup_seed():
    """Build the cloud-init seed ISO."""
    if SEED.exists():
        return
    if not SSH_KEY.exists():
        system("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", SSH_KEY)
    pubkey = SSH_KEY.with_suffix(".pub").read_text()
    # Written as JSON, which is valid YAML.
    if MACOS:
        nic = {
            "addresses": [f"{GUEST_IP}/24"],
            "routes": [{"to": "default", "via": f"{SUBNET}.1"}],
            "nameservers": {"addresses": [f"{SUBNET}.1"]},
        }
    else:
        nic = {"dhcp4": True}
    files = {
        # USER is the image's default user, with sudo and bash already.
        "user-data": "#cloud-config\n"
        + json.dumps({"ssh_authorized_keys": [pubkey]}),
        "meta-data": json.dumps({"instance-id": HOSTNAME, "local-hostname": HOSTNAME}),
        # Match the NIC by name, since vfkit picks a new MAC every start.
        "network-config": json.dumps(
            {"version": 2, "ethernets": {"nic": {"match": {"name": "en*"}, **nic}}}
        ),
    }
    SEED_DIR.mkdir(exist_ok=True)
    for name, text in files.items():
        (SEED_DIR / name).write_text(text)
    # cloud-init looks for the volume label "cidata".
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
    """Write an ssh config for the guest, also usable by hand or through
    `Include .../vm/*/ssh_config` in ~/.ssh/config. Host keys change on every
    reset, so they aren't checked, and connections aren't shared, since a
    stopped VM would leave the shared one hanging."""
    SSH_CONFIG.write_text(
        f"Host {HOSTNAME}\n"
        f"  HostName {SSH_HOST}\n"
        f"  Port {SSH_PORT}\n"
        f"  User {USER}\n"
        f"  IdentityFile {SSH_KEY}\n"
        "  IdentitiesOnly yes\n"
        "  StrictHostKeyChecking no\n"
        "  UserKnownHostsFile /dev/null\n"
        "  LogLevel ERROR\n"
        "  ControlPath none\n"
    )


def setup():
    """Prepare everything `start` needs."""
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    setup_deps()
    setup_kvm()
    setup_disk()
    setup_seed()
    setup_ssh_config()


def qemu_cmd():
    """QEMU, forwarding localhost:SSH_PORT to the guest's sshd."""
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
    """vfkit, with the guest at GUEST_IP on vmnet's NAT."""
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
    """SIGTERM the VM, which pulls the plug, and wait for it to exit."""
    pid = vm_pid()
    if pid is None:
        print("VM not running")
        return
    os.kill(pid, signal.SIGTERM)
    while alive(pid):
        time.sleep(0.1)
    print("VM stopped")


def reset():
    """Stop the VM and delete its files, keeping the base image."""
    stop()
    shutil.rmtree(INSTANCE, ignore_errors=True)


def sshd_up():
    """True once sshd sends its banner. A TCP connect alone isn't enough:
    QEMU's port forward accepts it before the guest is listening."""
    try:
        with socket.create_connection((SSH_HOST, SSH_PORT), timeout=2) as conn:
            return conn.recv(4) == b"SSH-"
    except OSError:
        return False


def ssh():
    """Wait for sshd, then open a shell."""
    print("Waiting for SSH...", flush=True)
    for _ in range(120):
        if sshd_up():
            break
        time.sleep(1)
    else:
        sys.exit(f"Timed out waiting for SSH (see {CONSOLE})")

    # A nonzero exit from the shell isn't an error.
    system("ssh", "-F", SSH_CONFIG, HOSTNAME, check=False)


def main():
    cmds = {f.__name__: f for f in (setup, start, ssh, stop, reset)}
    parser = argparse.ArgumentParser(
        description="Run an Ubuntu VM (vfkit on macOS, QEMU on Linux)."
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
