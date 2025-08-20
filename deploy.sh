#!/usr/bin/env bash
# Deploy direkt aus ./site auf GitHub (Repo: pama05/qr-present, Branch: main)
# Funktioniert mit HTTPS (PAT) oder SSH.
set -euo pipefail

REPO_URL_DEFAULT="https://github.com/pama05/qr-present.git"   # SSH: git@github.com:pama05/qr-present.git
BRANCH_DEFAULT="main"
SITE_DIR_DEFAULT="site"

REPO_URL="${1:-$REPO_URL_DEFAULT}"
BRANCH="${2:-$BRANCH_DEFAULT}"
SITE_DIR="${3:-$SITE_DIR_DEFAULT}"

echo "Repo URL : $REPO_URL"
echo "Branch   : $BRANCH"
echo "Site dir : $SITE_DIR"
echo

command -v git >/dev/null || { echo "ERROR: git nicht gefunden."; exit 1; }

# 1) Quelle prüfen
[ -d "$SITE_DIR" ] || { echo "ERROR: Ordner '$SITE_DIR' nicht gefunden. Erst bauen!"; exit 1; }
if [ -z "$(find "$SITE_DIR" -mindepth 1 -not -name '.DS_Store' -print -quit)" ]; then
  echo "ERROR: '$SITE_DIR' ist leer. Erst bauen!"
  exit 1
fi

# 2) In site/ wechseln und Repo initialisieren/verbinden
cd "$SITE_DIR"

# .nojekyll sicherstellen
[ -f ".nojekyll" ] || touch ".nojekyll"

if [ ! -d ".git" ]; then
  echo "→ git init in $(pwd)"
  git init
fi

# Aktuellen Branch setzen (macht nichts, wenn bereits so)
git checkout -B "$BRANCH"

# Remote setzen/aktualisieren
if git remote | grep -q "^origin$"; then
  git remote set-url origin "$REPO_URL"
else
  git remote add origin "$REPO_URL"
fi

# 3) Falls Remote-Branch existiert, Historie integrieren (avoid non-fast-forward errors)
echo "→ Prüfe Remote-Branch…"
if git ls-remote --exit-code --heads origin "$BRANCH" >/dev/null 2>&1; then
  echo "→ Remote-Branch existiert. Hole und rebase…"
  git fetch origin "$BRANCH"
  # Unrelated histories möglich (wenn site/ neu initialisiert wurde)
  git pull --rebase --allow-unrelated-histories origin "$BRANCH" || true
else
  echo "→ Remote-Branch existiert noch nicht (oder kein Zugriff)."
fi

# 4) Dateien hinzufügen & committen
git add -A
if git diff --cached --quiet; then
  echo "✓ Keine Änderungen – nichts zu committen."
else
  git commit -m "Deploy site ($(date '+%Y-%m-%d %H:%M:%S'))"
fi

# 5) Push
echo "→ Push nach $BRANCH …"
git push -u origin "$BRANCH"

# 6) Hinweis auf die Pages-URL
OWNER="pama05"
REPO="qr-present"
echo
echo "Fertig! Besuche (nach dem Pages-Build): https://${OWNER}.github.io/${REPO}"
