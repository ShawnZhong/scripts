curl -fsSL https://claude.ai/install.sh | bash

echo '{"includeCoAuthoredBy": false}' > ~/.claude/settings.json
# echo "$(jq '.includeCoAuthoredBy = false' ~/.claude/settings.json)" > ~/.claude/settings.json
