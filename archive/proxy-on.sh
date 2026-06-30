#!/usr/bin/env bash
set -euo pipefail

# env vars only persist if you `source` this script:
#   source proxy-on.sh
export http_proxy=http://squid.cs.wisc.edu:3128
export https_proxy=$http_proxy
export ftp_proxy=$http_proxy

# write both apt proxy lines in one file (single `tee`, no overwrite)
sudo tee /etc/apt/apt.conf > /dev/null <<'EOF'
Acquire::http::Proxy "http://squid.cs.wisc.edu:3128";
Acquire::https::Proxy "http://squid.cs.wisc.edu:3128";
EOF

git config --global http.proxy http://squid.cs.wisc.edu:3128
git config --global https.proxy http://squid.cs.wisc.edu:3128
