#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "$(date -Iseconds) Starting reddit-daily-rss build"

# No git in the loop: this repo no longer publishes to GitHub Pages. `personal-feed`
# reads docs/*.xml off disk directly, so the build just regenerates the local feeds.
python3 scripts/build_feed.py

echo "$(date -Iseconds) Done — feeds written to docs/"
