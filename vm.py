#!/usr/bin/env python3

import argparse
import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

RELEASE = "26.04"  # Ubuntu version
CPUS = "2"
MEM = "4096"  # MiB
DISK = "20G"
SSH_PORT = "2222"
USER = "ubuntu"
HOSTNAME = "ubuntu-vm"

MACOS = platform.system() == "Darwin"

HOST = platform.machine()
ARCH, QEMU = {
    "x86_64": ("amd64", "qemu-system-x86_64"),
    "aarch64": ("arm64", "qemu-system-aarch64"),
    "arm64": ("arm64", "qemu-system-aarch64"),
}.get(HOST) or sys.exit(f"Unsupported host architecture: {HOST}")

KVM = Path("/dev/kvm")

VM_DIR = Path("vm").resolve()
BASE = VM_DIR / f"ubuntu-{RELEASE}-server-cloudimg-{ARCH}.img"
DISK_IMG = VM_DIR / "disk.qcow2"
SEED = VM_DIR / "seed.img"
PIDFILE = VM_DIR / "qemu.pid"
CONSOLE = VM_DIR / "console.log"
# Writable per-VM copy of the arm64 UEFI variable store.
NVRAM = VM_DIR / "efi-vars.fd"

IMG_URL = (
    f"https://cloud-images.ubuntu.com/releases/{RELEASE}/release/"
    f"ubuntu-{RELEASE}-server-cloudimg-{ARCH}.img"
)

SSH_DIR = Path.home() / ".ssh"


def system(*cmd, check=True):
    print(f"+ {' '.join(map(str, cmd))}", flush=True)
    subprocess.run([str(c) for c in cmd], check=check)


def uefi():
    """Return (code, vars_template) UEFI firmware paths for arm64 guests.
    On macOS these ship with the Homebrew qemu formula; on Linux with AAVMF."""
    if MACOS:
        out = subprocess.run(["brew", "--prefix", "qemu"],
                             capture_output=True, text=True, check=True)
        share = Path(out.stdout.strip()) / "share" / "qemu"
        return share / "edk2-aarch64-code.fd", share / "edk2-arm-vars.fd"
    return (Path("/usr/share/AAVMF/AAVMF_CODE.fd"),
            Path("/usr/share/AAVMF/AAVMF_VARS.fd"))


def alive(p):
    """True if process p exists (portable replacement for /proc/<pid>)."""
    try:
        os.kill(p, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def pubkey():
    """Return the path to an SSH public key, generating one if none exists."""
    for name in ("id_ed25519", "id_rsa"):
        pub = SSH_DIR / f"{name}.pub"
        if pub.exists():
            return pub
    key = SSH_DIR / "id_ed25519"
    system("ssh-keygen", "-t", "ed25519", "-N", "", "-C", "vm.py", "-f", key)
    return key.with_suffix(".pub")


def private_key():
    return pubkey().with_suffix("")


def pid():
    """Return the running qemu PID, or None."""
    if not PIDFILE.exists():
        return None
    p = int(PIDFILE.read_text().strip())
    if alive(p):
        return p
    PIDFILE.unlink()
    return None


@dataclass
class Dep:
    """A host dependency. `check` is true when it's already present; what proves
    it present differs from the package name (e.g. qemu-img ships in qemu-utils),
    and the providing package differs per platform."""
    check: Callable[[], object]  # truthy when already present
    apt: str   # Debian/Ubuntu package
    brew: str  # Homebrew formula


# The host dependencies needed to run a VM, each with its per-platform package.
DEPS = [
    Dep(lambda: shutil.which(QEMU),
        "qemu-system-x86" if ARCH == "amd64" else "qemu-system-arm", "qemu"),
    Dep(lambda: shutil.which("qemu-img"), "qemu-utils", "qemu"),
    Dep(lambda: shutil.which("xorriso"), "xorriso", "xorriso"),
    # arm64 guests boot via UEFI. Linux needs the AAVMF firmware package; on
    # macOS the Homebrew qemu formula already bundles the edk2 firmware.
    Dep(lambda: MACOS or ARCH != "arm64" or uefi()[0].exists(),
        "qemu-efi-aarch64", "qemu"),
]


def setup_deps():
    """Install any missing host packages needed to run the VM."""
    missing = [d for d in DEPS if not d.check()]
    if not missing:
        return
    if MACOS:  # dict.fromkeys dedups (qemu provides several deps) and keeps order
        system("brew", "install", *dict.fromkeys(d.brew for d in missing))
    else:
        system("sudo", "apt-get", "update")
        system("sudo", "apt-get", "install", "-y", *dict.fromkeys(d.apt for d in missing))


def setup_kvm():
    """Relax /dev/kvm (root:kvm 0660) so this user can use KVM without root.
    Resets on reboot, but runs on every start, so it self-heals. macOS
    accelerates with Hypervisor.framework, which needs no device permission."""
    if MACOS:
        return
    if KVM.exists() and not os.access(KVM, os.R_OK | os.W_OK):
        system("sudo", "chmod", "666", KVM)
    if not os.access(KVM, os.R_OK | os.W_OK):
        print("/dev/kvm unavailable; using slow emulation.")


def setup_disk():
    """Download the cloud image and create this VM's copy-on-write overlay."""
    if not BASE.exists():
        system("curl", "-fL", "-o", BASE, IMG_URL)

    if not DISK_IMG.exists():
        system("qemu-img", "create", "-f", "qcow2", "-F", "qcow2",
               "-b", BASE, DISK_IMG, DISK)

    # arm64 needs a per-VM writable copy of the UEFI variable store to boot.
    if ARCH == "arm64" and not NVRAM.exists():
        shutil.copy(uefi()[1], NVRAM)


def setup_seed():
    """Build the cloud-init NoCloud seed ISO carrying the host's SSH key."""
    if SEED.exists():
        return
    key = pubkey().read_text().strip()
    user_data = VM_DIR / "user-data"
    user_data.write_text(
        "#cloud-config\n"
        f"hostname: {HOSTNAME}\n"
        "ssh_pwauth: false\n"
        "users:\n"
        f"  - name: {USER}\n"
        "    sudo: ALL=(ALL) NOPASSWD:ALL\n"
        "    shell: /bin/bash\n"
        "    ssh_authorized_keys:\n"
        f"      - {key}\n"
    )
    meta_data = VM_DIR / "meta-data"
    meta_data.write_text(
        f"instance-id: {HOSTNAME}\nlocal-hostname: {HOSTNAME}\n"
    )
    # The NoCloud datasource requires the volume label to be "cidata".
    system("xorriso", "-as", "genisoimage", "-output", SEED,
           "-volid", "cidata", "-joliet", "-rock", user_data, meta_data)


def setup():
    """Run every setup step: deps, KVM, disk, and seed."""
    VM_DIR.mkdir(parents=True, exist_ok=True)
    setup_deps()
    setup_kvm()
    setup_disk()
    setup_seed()


def start():
    if p := pid():
        print(f"VM already running (pid {p})")
    else:
        setup()
        machine = "q35" if ARCH == "amd64" else "virt"
        # macOS accelerates with Hypervisor.framework, Linux with KVM. HVF
        # requires -cpu host; -cpu max works under TCG/KVM but not HVF.
        accel = "hvf:tcg" if MACOS else "kvm:tcg"
        cpu = "host" if MACOS else "max"
        cmd = [
            QEMU,
            "-name", HOSTNAME,
            "-machine", f"type={machine},accel={accel}",
            "-cpu", cpu,
            "-smp", CPUS,
            "-m", MEM,
            "-display", "none",
            "-serial", f"file:{CONSOLE}",
            "-drive", f"if=virtio,format=qcow2,file={DISK_IMG}",
            "-drive", f"if=virtio,format=raw,file={SEED}",
            "-device", "virtio-net-pci,netdev=net0",
            "-netdev", f"user,id=net0,hostfwd=tcp::{SSH_PORT}-:22",
            "-pidfile", str(PIDFILE),
            "-daemonize",
        ]
        if ARCH == "arm64":
            # UEFI firmware: read-only code + this VM's writable variable store.
            cmd += [
                "-drive", f"if=pflash,format=raw,readonly=on,file={uefi()[0]}",
                "-drive", f"if=pflash,format=raw,file={NVRAM}",
            ]
        system(*cmd)

    ssh()


def stop():
    p = pid()
    if not p:
        print("VM not running")
        return
    print(f"+ kill {p}", flush=True)
    os.kill(p, 15)
    for _ in range(30):
        if not alive(p):
            break
        time.sleep(1)
    else:
        os.kill(p, 9)
    if PIDFILE.exists():
        PIDFILE.unlink()


def restart():
    stop()
    start()


def reset():
    """Wipe VM state (disk + seed) but keep the downloaded base image."""
    stop()
    for f in (DISK_IMG, SEED, CONSOLE, NVRAM):
        f.unlink(missing_ok=True)
    setup()


def ssh():
    """Wait for the guest's sshd to come up, then open an interactive shell."""
    target = ["-p", SSH_PORT, "-i", str(private_key()),
              "-o", "StrictHostKeyChecking=no",
              "-o", "UserKnownHostsFile=/dev/null",
              # Key-only: sshd is up before cloud-init injects the key, so until
              # it lands the server offers password auth. BatchMode keeps the
              # probe from blocking on that prompt, so the loop waits instead.
              "-o", "BatchMode=yes",
              "-o", "LogLevel=ERROR",
              f"{USER}@localhost"]

    print("Waiting for SSH...", flush=True)
    for _ in range(120):
        probe = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=2", *target, "true"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if probe.returncode == 0:
            break
        time.sleep(2)
    else:
        sys.exit(f"Timed out waiting for SSH (see {CONSOLE})")

    # check=False: exiting the shell with a nonzero status is normal, not an error.
    system("ssh", *target, check=False)


def main():
    cmds = {
        "setup": setup,
        "start": start,
        "stop": stop,
        "restart": restart,
        "reset": reset,
    }
    parser = argparse.ArgumentParser(description="Run an Ubuntu cloud image in QEMU.")
    parser.add_argument(
        "command", nargs="?", default="start", choices=cmds,
        help="subcommand to run (default: start)",
    )
    cmds[parser.parse_args().command]()


if __name__ == "__main__":
    main()
