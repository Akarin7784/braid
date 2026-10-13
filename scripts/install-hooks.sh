#!/usr/bin/env bash
# Point git at the repo's tracked hooks (shared by all worktrees).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
chmod +x scripts/hooks/*
git config core.hooksPath scripts/hooks
echo "已启用 scripts/hooks（core.hooksPath）。"
