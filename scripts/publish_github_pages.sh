#!/usr/bin/env bash
# Publish the self-contained dashboard to the GitHub Pages remote.
#
# Required secret (Cursor Environment / Secrets — never paste into chat):
#   PAGES_GITHUB_TOKEN  — GitHub PAT with contents:write on the Pages repo
# Optional:
#   PAGES_GITHUB_URL    — defaults to https://github.com/alexeigudkov2018-jpg/bond-purchase-agent.git
#   GH_TOKEN            — fallback if PAGES_GITHUB_TOKEN is unset
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PAGES_URL="${PAGES_GITHUB_URL:-https://github.com/alexeigudkov2018-jpg/bond-purchase-agent.git}"
TOKEN="${PAGES_GITHUB_TOKEN:-${GH_TOKEN:-}}"

if [[ -z "${TOKEN}" ]]; then
  echo "Missing PAGES_GITHUB_TOKEN (or GH_TOKEN)."
  echo "Add a GitHub PAT in Cursor → Environment → Secrets as PAGES_GITHUB_TOKEN, then re-run:"
  echo "  bash scripts/publish_github_pages.sh"
  exit 2
fi

python3 scripts/build_dashboard.py

if [[ ! -f dashboard.html || ! -f index.html ]]; then
  echo "dashboard.html / index.html missing after build" >&2
  exit 1
fi
if ! cmp -s dashboard.html index.html; then
  echo "dashboard.html and index.html differ after build" >&2
  exit 1
fi

# Push URL embeds the token for this invocation only.
path_part="${PAGES_URL#https://github.com/}"
AUTH_URL="https://x-access-token:${TOKEN}@github.com/${path_part}"

if git remote get-url pages >/dev/null 2>&1; then
  git remote set-url pages "${PAGES_URL}"
else
  git remote add pages "${PAGES_URL}"
fi

echo "Pushing HEAD → pages/main (${PAGES_URL})"
git push "${AUTH_URL}" "HEAD:refs/heads/main"
echo "Done. Enable GitHub Pages on main / root if not already on."
