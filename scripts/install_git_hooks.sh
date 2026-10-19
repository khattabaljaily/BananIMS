#!/usr/bin/env bash
# يفعّل git hooks الخاصة بالمشروع (scripts/git-hooks) لهذا الـ clone.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
chmod +x scripts/git-hooks/*
git config core.hooksPath scripts/git-hooks
echo "✓ git hooks مفعّلة: $(git config core.hooksPath)"
