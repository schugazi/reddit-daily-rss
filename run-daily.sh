#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "$(date -Iseconds) Starting reddit-daily-rss build"

git pull --ff-only

python3 scripts/build_feed.py

git add docs/
if git diff --cached --quiet; then
  echo "No changes to commit."
  exit 0
fi

git commit -m "Update daily feed"
git push
echo "$(date -Iseconds) Done — changes pushed"
