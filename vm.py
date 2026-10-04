#!/usr/bin/env python3

import argparse
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
SSH_PORT = "2200"
USER = "ubuntu"
HOSTNAME = "ubuntu-vm"

MACOS = platform.system() == "Darwin"

HOST = platform.machine()
ARCH, QEMU = {
    "x86_64": ("amd64", "qemu-system-x86_64"),
    "aarch64": ("arm64", "qemu-system-aarch64"),
    "arm64": ("arm64", "qemu-system-aarch64"),
}.get(HOST) or sys.exit(f"Unsupported host architecture: {HOST}")

IMG_URL = f"https://cloud-images.ubuntu.com/minimal/releases/noble/release/ubuntu-24.04-minimal-cloudimg-{ARCH}.img"

VM_DIR = Path("vm").resolve()
BASE = VM_DIR / Path(IMG_URL).name
DISK_IMG = VM_DIR / "disk.qcow2"
SEED = VM_DIR / "seed.img"
PIDFILE = VM_DIR / "qemu.pid"
CONSOLE = VM_DIR / "console.log"

SSH_DIR = Path.home() / ".ssh"


def system(*cmd, check=True):
    print(f"+ {' '.join(map(str, cmd))}", flush=True)
    subprocess.run([str(c) for c in cmd], check=check)


def uefi():
    """Return the arm64 UEFI firmware image, loaded via -bios to boot the guest.
    On macOS it ships with the Homebrew qemu formula; on Linux with AAVMF.
    Variables are volatile (no NVRAM store), which a cloud image doesn't need."""
    if MACOS:
        out = subprocess.run(
            ["brew", "--prefix", "qemu"], capture_output=True, text=True, check=True
        )
        return Path(out.stdout.strip()) / "share" / "qemu" / "edk2-aarch64-code.fd"
    return Path("/usr/share/AAVMF/AAVMF_CODE.fd")


def alive(pid):
    """True if the process exists (portable replacement for /proc/<pid>)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


def vm_pid():
    """The live QEMU PID, or None. A stale pidfile reads as None; qemu's
    -pidfile takes a lock and overwrites it on the next start."""
    try:
        pid = int(PIDFILE.read_text())
    except (FileNotFoundError, ValueError):
        return None
    return pid if alive(pid) else None


def terminate(timeout=30):
    """SIGTERM the VM, escalating to SIGKILL after `timeout` seconds, then
    clear the pidfile. Returns False if nothing was running."""
    pid = vm_pid()
    if pid is None:
        return False
    os.kill(pid, signal.SIGTERM)
    for _ in range(timeout):
        if not alive(pid):
            break
        time.sleep(1)
    else:
        os.kill(pid, signal.SIGKILL)
    PIDFILE.unlink(missing_ok=True)
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


# The host dependencies needed to run a VM, as
# (check: truthy when already present, apt package, brew formula).
DEPS = [
    (
        lambda: shutil.which(QEMU),
        "qemu-system-x86" if ARCH == "amd64" else "qemu-system-arm",
        "qemu",
    ),
    (lambda: shutil.which("qemu-img"), "qemu-utils", "qemu"),
    (lambda: shutil.which("xorriso"), "xorriso", "xorriso"),
    # arm64 guests boot via UEFI. Linux needs the AAVMF firmware package; on
    # macOS the Homebrew qemu formula already bundles the edk2 firmware.
    (lambda: MACOS or ARCH != "arm64" or uefi().exists(), "qemu-efi-aarch64", "qemu"),
]


def setup_deps():
    """Install any missing host packages needed to run the VM."""
    missing = [(apt, brew) for check, apt, brew in DEPS if not check()]
    if not missing:
        return
    if MACOS:
        system("brew", "install", *dict.fromkeys(brew for _, brew in missing))
    else:
        system("sudo", "apt-get", "update")
        system(
            "sudo", "apt-get", "install", "-y", *dict.fromkeys(apt for apt, _ in missing)
        )


def setup_kvm():
    """Relax /dev/kvm (root:kvm 0660) so this user can use KVM without root.
    Resets on reboot, but runs on every start, so it self-heals. macOS
    accelerates with Hypervisor.framework, which needs no device permission."""
    if MACOS:
        return
    KVM = Path("/dev/kvm")
    if KVM.exists() and not os.access(KVM, os.R_OK | os.W_OK):
        system("sudo", "chmod", "666", KVM)
    if not os.access(KVM, os.R_OK | os.W_OK):
        print("/dev/kvm unavailable; using slow emulation.")


def setup_disk():
    """Download the cloud image and create this VM's copy-on-write overlay."""
    if not BASE.exists():
        system("curl", "-fL", "-o", BASE, IMG_URL)

    if not DISK_IMG.exists():
        system(
            "qemu-img",
            "create",
            "-f",
            "qcow2",
            "-F",
            "qcow2",
            "-b",
            BASE,
            DISK_IMG,
            DISK,
        )


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
    meta_data.write_text(f"instance-id: {HOSTNAME}\nlocal-hostname: {HOSTNAME}\n")
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
        user_data,
        meta_data,
    )


def setup():
    """Run every setup step: deps, KVM, disk, and seed."""
    VM_DIR.mkdir(parents=True, exist_ok=True)
    setup_deps()
    setup_kvm()
    setup_disk()
    setup_seed()


def start():
    if pid := vm_pid():
        print(f"VM already running (pid {pid})")
    else:
        setup()
        machine = "q35" if ARCH == "amd64" else "virt"
        # macOS accelerates with Hypervisor.framework, Linux with KVM. HVF
        # requires -cpu host; -cpu max works under TCG/KVM but not HVF.
        accel = "hvf:tcg" if MACOS else "kvm:tcg"
        cpu = "host" if MACOS else "max"
        cmd = [
            QEMU,
            "-name",
            HOSTNAME,
            "-machine",
            f"type={machine},accel={accel}",
            "-cpu",
            cpu,
            "-smp",
            CPUS,
            "-m",
            MEM,
            "-display",
            "none",
            "-serial",
            f"file:{CONSOLE}",
            "-drive",
            f"if=virtio,format=qcow2,file={DISK_IMG}",
            "-drive",
            f"if=virtio,format=raw,file={SEED}",
            "-device",
            "virtio-net-pci,netdev=net0",
            "-netdev",
            f"user,id=net0,hostfwd=tcp:127.0.0.1:{SSH_PORT}-:22",
            "-pidfile",
            PIDFILE,
            "-daemonize",
        ]
        if ARCH == "arm64":
            cmd += ["-bios", str(uefi())]  # UEFI firmware to boot the guest
        system(*cmd)


def stop():
    print("VM stopped" if terminate() else "VM not running")


def restart():
    stop()
    start()


def reset():
    """Wipe VM state (disk + seed) but keep the downloaded base image."""
    stop()
    for f in (DISK_IMG, SEED, CONSOLE):
        f.unlink(missing_ok=True)
    setup()


def ssh():
    """Wait for the guest's sshd to come up, then open an interactive shell."""
    target = [
        "-p",
        SSH_PORT,
        "-i",
        pubkey().with_suffix(""),
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "BatchMode=yes",
        "-o",
        "LogLevel=ERROR",
        f"{USER}@localhost",
    ]

    print("Waiting for SSH...", flush=True)
    for _ in range(120):
        probe = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=2", *target, "true"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
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
        "ssh": ssh,
        "stop": stop,
        "restart": restart,
        "reset": reset,
    }
    parser = argparse.ArgumentParser(description="Run an Ubuntu cloud image in QEMU.")
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
