#!/usr/bin/env bash
set -euo pipefail

# env vars only clear if you `source` this script:
#   source proxy-off.sh
unset http_proxy https_proxy ftp_proxy || true

sudo rm -f /etc/apt/apt.conf

git config --global --unset http.proxy || true
git config --global --unset https.proxy || true
