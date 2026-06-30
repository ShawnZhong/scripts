#!/usr/bin/env python3

import os
import subprocess
import sys
from pathlib import Path


def system(*cmd):
    print(f"+ {' '.join(cmd)}", flush=True)
    subprocess.run(cmd)


def main():
    if os.geteuid() != 0:
        sys.exit("Must run as root")

    st = os.stat("/")
    p = Path(f"/sys/dev/block/{os.major(st.st_dev)}:{os.minor(st.st_dev)}").resolve()

    # Grow the partition
    num = (p / "partition").read_text().strip()
    system("growpart", f"/dev/{p.parent.name}", num)

    # Resize the filesystem
    system("resize2fs", f"/dev/{p.name}")

    # Show the new size
    system("df", "-h", "/")


if __name__ == "__main__":
    main()
