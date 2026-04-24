#!/bin/bash

# release.sh — Automazione della release per NotePadPQ
# Istruzioni: rendi lo script eseguibile con 'chmod +x release.sh'

set -e

# 1. Chiedi la nuova versione all'utente
echo "=== Creazione Nuova Release per NotePadPQ ==="
read -p "Inserisci il numero della nuova versione (es. 0.2.1): " VERSION

if [[ -z "$VERSION" ]]; then
    echo "Errore: La versione non può essere vuota."
    exit 1
fi

# Aggiunge il prefisso 'v' per i tag di git se non presente
TAG_VERSION="v$VERSION"

echo "Aggiornamento dei sorgenti alla versione $VERSION..."

# 2. Aggiorna la versione in main.py
# Cerca la riga app.setApplicationVersion("...")
sed -i "s/app.setApplicationVersion(\".*\")/app.setApplicationVersion(\"$VERSION\")/g" main.py

# 3. Aggiorna la versione in ui/main_window.py
# Cerca la riga APP_VERSION = "..."
sed -i "s/APP_VERSION = \".*\"/APP_VERSION = \"$VERSION\"/g" ui/main_window.py

echo "File aggiornati correttamente."

# 4. Operazioni Git
echo "Preparazione del commit e del tag..."

git add main.py ui/main_window.py
git commit -m "chore: release $VERSION"

echo "Creazione del tag $TAG_VERSION..."
git tag -a "$TAG_VERSION" -m "Versione $VERSION"

# 5. Push su GitHub
echo "Invio dei dati a GitHub (main e tag)..."
git push origin main
git push origin "$TAG_VERSION"

# 5. Push su GitHub
echo "Invio dei dati a GitHub (main e tag)..."
git push origin main
git push origin "$TAG_VERSION"

# 6. Creazione della Release Ufficiale su GitHub
echo "Creazione della Release su GitHub..."
if command -v gh &> /dev/null; then
    gh release create "$TAG_VERSION" --title "NotePadPQ $VERSION" --generate-notes
    echo "Release pubblicata con successo su GitHub!"
else
    echo "ATTENZIONE: GitHub CLI (gh) non trovata."
    echo "Ora puoi andare su https://github.com/buzzqw/NotePadPQ/releases per pubblicare la release ufficiale."
fi

echo ""
echo "=== Successo! ==="