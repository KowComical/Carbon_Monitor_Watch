#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python tools/sync_logs.py

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Static data is updated locally. Skipping GitHub Pages publish because this directory is not a git repo."
  exit 0
fi

if ! git remote get-url origin >/dev/null 2>&1; then
  echo "Static data is updated locally. Skipping GitHub Pages publish because git remote origin is not set."
  exit 0
fi

git add static

if git diff --cached --quiet; then
  echo "No static site changes to publish."
else
  git commit -m "Update Carbon Monitor Watch data $(date +%F)"
  git push origin HEAD
fi

git subtree push --prefix static origin gh-pages
