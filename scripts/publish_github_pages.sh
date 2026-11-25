#!/usr/bin/env bash
# Publish the self-contained dashboard to the GitHub Pages remote.
#
# Token resolution (first match wins):
#   1. $PAGES_GITHUB_TOKEN / $GH_TOKEN
#   2. repo-local .env (PAGES_GITHUB_TOKEN=… / GH_TOKEN=…)
#   3. ~/.git-credentials entry for github.com
#
# Optional:
#   PAGES_GITHUB_URL  — defaults to https://github.com/alexeigudkov2018-jpg/bond-purchase-agent.git
#   --no-build        — skip rebuild (used when called from build_dashboard.py)
#   SKIP_PAGES_PUBLISH=1 inside a nested build prevents re-entry
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PAGES_URL="${PAGES_GITHUB_URL:-https://github.com/alexeigudkov2018-jpg/bond-purchase-agent.git}"
NO_BUILD=0
for arg in "$@"; do
  case "$arg" in
    --no-build) NO_BUILD=1 ;;
  esac
done

# Load repo-local .env without printing values.
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

TOKEN="${PAGES_GITHUB_TOKEN:-${GH_TOKEN:-}}"

if [[ -z "${TOKEN}" && -f "${HOME}/.git-credentials" ]]; then
  # Prefer x-access-token / password field from a github.com credential line.
  TOKEN="$(
    python3 - <<'PY'
from pathlib import Path
import re
text = Path.home().joinpath(".git-credentials").read_text(encoding="utf-8", errors="ignore")
for line in text.splitlines():
    line = line.strip()
    if "github.com" not in line:
        continue
    m = re.match(r"https?://([^:@/]+):([^@/]+)@github\.com", line)
    if m:
        user, password = m.group(1), m.group(2)
        print(password if user.lower() in {"x-access-token", "token", "oauth2", "git"} else password)
        break
    m = re.match(r"https?://([^@/]+)@github\.com", line)
    if m:
        print(m.group(1))
        break
PY
  )"
fi

if [[ -z "${TOKEN}" ]]; then
  echo "Missing PAGES_GITHUB_TOKEN (or GH_TOKEN / .env / ~/.git-credentials)."
  echo "Add a GitHub PAT in Cursor → Environment → Secrets as PAGES_GITHUB_TOKEN, then re-run:"
  echo "  bash scripts/publish_github_pages.sh"
  exit 2
fi

if [[ "${NO_BUILD}" -eq 0 ]]; then
  # Prevent build_dashboard.py from calling us back while we rebuild.
  SKIP_PAGES_PUBLISH=1 python3 scripts/build_dashboard.py
fi

if [[ ! -f dashboard.html || ! -f index.html ]]; then
  echo "dashboard.html / index.html missing after build" >&2
  exit 1
fi
if ! cmp -s dashboard.html index.html; then
  echo "dashboard.html and index.html differ after build" >&2
  exit 1
fi

# Commit rebuilt twins when dirty so Pages gets the fresh HTML, not stale HEAD.
if [[ -n "$(git status --porcelain -- dashboard.html index.html 2>/dev/null || true)" ]]; then
  git add dashboard.html index.html
  git commit -m "dashboard: rebuild HTML twins for GitHub Pages" || true
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
# Keep Origin main aligned when we are already on main (best-effort).
if [[ "$(git rev-parse --abbrev-ref HEAD)" == "main" ]]; then
  git push origin HEAD:main || echo "pages: origin push skipped/failed (non-fatal for Pages)"
fi
echo "Done. Site: https://alexeigudkov2018-jpg.github.io/bond-purchase-agent/"
