#!/bin/bash

# retroactive_notes.sh — Riscrive le note di tutte le release GitHub
# usando i commit tra un tag e il precedente.
#
# Uso:
#   bash retroactive_notes.sh           # anteprima + conferma per ogni release
#   bash retroactive_notes.sh --dry-run # solo anteprima, nessuna modifica
#   bash retroactive_notes.sh --yes     # aggiorna tutto senza chiedere
#
# Richiede: git, gh (GitHub CLI autenticato)

set -e

DRY_RUN=0
AUTO_YES=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        --yes)     AUTO_YES=1 ;;
    esac
done

if [[ $DRY_RUN -eq 1 ]]; then
    echo "=== MODALITÀ DRY-RUN: nessuna modifica verrà effettuata ==="
fi
echo ""

# Raccoglie tutti i tag in ordine di versione
mapfile -t TAGS < <(git tag --sort=version:refname)

if [[ ${#TAGS[@]} -eq 0 ]]; then
    echo "Nessun tag trovato nel repository."
    exit 1
fi

echo "Tag trovati: ${TAGS[*]}"
echo ""

# Recupera la lista delle release esistenti su GitHub (una per riga)
echo "Recupero lista release da GitHub..."
GH_RELEASES=$(gh release list --limit 100 --json tagName --jq '.[].tagName' 2>/dev/null || echo "")
if [[ -z "$GH_RELEASES" ]]; then
    echo "ATTENZIONE: nessuna release trovata su GitHub (o gh non autenticato)."
fi
echo ""

NOTES_FILE=$(mktemp /tmp/notepadpq_notes_XXXX.md)
trap 'rm -f "$NOTES_FILE"' EXIT

UPDATED=0
SKIPPED=0
NO_RELEASE=0

for i in "${!TAGS[@]}"; do
    TAG="${TAGS[$i]}"
    VERSION="${TAG#v}"

    if [[ $i -eq 0 ]]; then
        PREV_TAG=""
    else
        PREV_TAG="${TAGS[$i-1]}"
    fi

    # Raccoglie i commit nel range, filtra il commit di release
    if [[ -z "$PREV_TAG" ]]; then
        RAW=$(git log "${TAG}" --pretty=format:"%s" --no-merges 2>/dev/null || true)
    else
        RAW=$(git log "${PREV_TAG}..${TAG}" --pretty=format:"%s" --no-merges 2>/dev/null || true)
    fi
    RAW=$(echo "$RAW" | grep -v "^chore: release" || true)

    if [[ -z "$RAW" ]]; then
        CHANGELOG="- (nessun commit rilevante)"
    else
        CHANGELOG=$(echo "$RAW" | sed 's/^/- /')
    fi

    # Controlla se la release esiste su GitHub
    if echo "$GH_RELEASES" | grep -qx "$TAG"; then
        HAS_RELEASE=1
    else
        HAS_RELEASE=0
    fi

    # Anteprima
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    if [[ $HAS_RELEASE -eq 0 ]]; then
        echo "  Release : $TAG  [nessuna release GitHub — verrà saltata]"
    else
        echo "  Release : $TAG"
    fi
    if [[ -z "$PREV_TAG" ]]; then
        echo "  Range   : inizio → $TAG"
    else
        echo "  Range   : $PREV_TAG → $TAG"
    fi
    echo ""
    echo "## Novità in $VERSION"
    echo ""
    echo "$CHANGELOG"
    echo ""

    if [[ $DRY_RUN -eq 1 ]]; then
        continue
    fi

    # Salta se non esiste la release su GitHub
    if [[ $HAS_RELEASE -eq 0 ]]; then
        NO_RELEASE=$((NO_RELEASE + 1))
        continue
    fi

    # Conferma interattiva
    if [[ $AUTO_YES -eq 0 ]]; then
        read -p "  Aggiornare la release $TAG su GitHub? [s/N/q] " CHOICE
        case "$CHOICE" in
            s|S) ;;
            q|Q) echo "Interrotto."; exit 0 ;;
            *)   echo "  Saltata."; SKIPPED=$((SKIPPED + 1)); continue ;;
        esac
    fi

    # Scrive le note e aggiorna
    {
        echo "## Novità in $VERSION"
        echo ""
        echo "$CHANGELOG"
    } > "$NOTES_FILE"

    if gh release edit "$TAG" --notes-file "$NOTES_FILE" > /dev/null 2>&1; then
        echo "  ✓ Release $TAG aggiornata."
        UPDATED=$((UPDATED + 1))
    else
        echo "  ✗ Errore nell'aggiornamento di $TAG."
        SKIPPED=$((SKIPPED + 1))
    fi
    echo ""
done

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [[ $DRY_RUN -eq 1 ]]; then
    echo "Dry-run completato. Nessuna release modificata."
else
    echo "Completato."
    echo "  Aggiornate      : $UPDATED"
    echo "  Saltate (utente): $SKIPPED"
    echo "  Senza release   : $NO_RELEASE"
fi
