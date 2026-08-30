#!/bin/bash
set -e

echo "=== Git Status ==="
git status

echo ""
echo "=== Changes to commit ==="
git diff --stat HEAD

echo ""
read -p "Commit message: " commit_msg

if [ -z "$commit_msg" ]; then
  echo "Aborted: no commit message"
  exit 1
fi

git add -A
git commit -m "$commit_msg"
git push

echo "✓ Committed and pushed"
