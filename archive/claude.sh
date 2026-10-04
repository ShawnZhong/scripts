#!/usr/bin/env bash
set -euo pipefail

curl -fsSL https://claude.ai/install.sh | bash

mkdir -p ~/.claude
echo '{"includeCoAuthoredBy": false}' > ~/.claude/settings.json
# echo "$(jq '.includeCoAuthoredBy = false' ~/.claude/settings.json)" > ~/.claude/settings.json
