#!/bin/bash
# versiona.sh — Automazione release universale
# Rileva automaticamente: nome progetto, file di versione, piattaforma (GitHub/GitLab),
# branch principale e lingua delle note di rilascio.
# Uso: bash versiona.sh [--dry-run]
# Opzionale: ANTHROPIC_API_KEY per note AI, .versiona.conf per overrides locali

set -e

# ── Colori ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
info() { echo -e "${CYAN}ℹ ${RESET}$*"; }
ok()   { echo -e "${GREEN}✔ ${RESET}$*"; }
warn() { echo -e "${YELLOW}⚠ ${RESET}$*" >&2; }
err()  { echo -e "${RED}✘ ${RESET}$*" >&2; exit 1; }
sep()  { echo -e "${BOLD}──────────────────────────────────────────────${RESET}"; }

echo -e "${CYAN}🚀 Avvio analisi del progetto...${RESET}"

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
fi

# ── Verifica git ──────────────────────────────────────────────────────────────
git rev-parse --git-dir &>/dev/null || err "Non sei in un repository git."
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# ── Carica config locale (.versiona.conf) ─────────────────────────────────────
RELEASE_LANG=""
MAIN_BRANCH=""
EXTRA_UPDATE_FILES=()
if [[ -f ".versiona.conf" ]]; then
    source ".versiona.conf"
fi

# ── Rileva nome progetto ──────────────────────────────────────────────────────
detect_project_name() {
    local remote_url
    remote_url=$(git remote get-url origin 2>/dev/null || true)
    if [[ -n "$remote_url" ]]; then
        basename "$remote_url" .git
        return
    fi
    basename "$(pwd)"
}
PROJECT_NAME=$(detect_project_name)

# ── Rileva branch principale ──────────────────────────────────────────────────
detect_main_branch() {
    if [[ -n "$MAIN_BRANCH" ]]; then
        echo "$MAIN_BRANCH"
        return
    fi
    local ref
    ref=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's|.*/||' || true)
    if [[ -n "$ref" ]]; then
        echo "$ref"
        return
    fi
    for b in main master develop; do
        if git show-ref --verify --quiet "refs/heads/$b"; then
            echo "$b"
            return
        fi
    done
    git rev-parse --abbrev-ref HEAD
}
MAIN_BRANCH=$(detect_main_branch)

# ── Rileva piattaforma remote ─────────────────────────────────────────────────
detect_platform() {
    local url
    url=$(git remote get-url origin 2>/dev/null || true)
    if [[ "$url" == *"github.com"* ]]; then echo "github"
    elif [[ "$url" == *"gitlab"* ]];   then echo "gitlab"
    else                                    echo "none"
    fi
}
PLATFORM=$(detect_platform)

# ── Rileva lingua note di rilascio ────────────────────────────────────────────
detect_language() {
    if [[ -n "$RELEASE_LANG" ]]; then
        echo "$RELEASE_LANG"
        return
    fi
    if ls MANUAL_IT.md MANUALE.md 2>/dev/null | grep -q .; then
        echo "it"; return
    fi
    if grep -q "Italiano\|Funzionalità\|Installazione" README.md 2>/dev/null; then
        echo "it"; return
    fi
    echo "en"
}
LANG_NOTES=$(detect_language)

# ── Rileva file di versione e versione corrente ───────────────────────────────
declare -a VERSION_FILES=()

detect_version_files() {
    if [[ -f "package.json" ]] && grep -q '"version"' package.json 2>/dev/null; then
        VERSION_FILES+=("package.json:json")
    fi
    if [[ -f "pyproject.toml" ]] && grep -qE '^\s*version\s*=' pyproject.toml 2>/dev/null; then
        VERSION_FILES+=("pyproject.toml:toml")
    fi
    if [[ -f "setup.py" ]] && grep -qE "version\s*=" setup.py 2>/dev/null; then
        VERSION_FILES+=("setup.py:setup_py")
    fi
    if [[ -f "setup.cfg" ]] && grep -qE "^version\s*=" setup.cfg 2>/dev/null; then
        VERSION_FILES+=("setup.cfg:ini")
    fi
    if [[ -f "Cargo.toml" ]] && grep -qE '^version\s*=' Cargo.toml 2>/dev/null; then
        VERSION_FILES+=("Cargo.toml:toml")
    fi
    
    # Usa git grep invece di grep normale: ignora in automatico tutte le cartelle in .gitignore (.claude, ecc.)
    while IFS= read -r f; do
        [[ -n "$f" ]] && VERSION_FILES+=("$f:py_appver")
    done < <(git grep -l 'APP_VERSION\s*=\s*"' -- '*.py' 2>/dev/null | head -3 || true)
             
    while IFS= read -r f; do
        [[ -n "$f" ]] && VERSION_FILES+=("$f:py_dunder")
    done < <(git grep -l '__version__\s*=\s*"' -- '*.py' 2>/dev/null | head -3 || true)
             
    while IFS= read -r f; do
        [[ -n "$f" ]] && VERSION_FILES+=("$f:qt_ver")
    done < <(git grep -l 'setApplicationVersion\s*(' -- '*.py' 2>/dev/null | head -3 || true)
             
    if [[ -f "VERSION" ]]; then
        VERSION_FILES+=("VERSION:plain")
    fi
    if [[ -f "README.md" ]] && grep -q 'badge/Version-' README.md 2>/dev/null; then
        VERSION_FILES+=("README.md:badge")
    fi
    for f in "${EXTRA_UPDATE_FILES[@]:-}"; do
        if [[ -f "$f" ]]; then
            VERSION_FILES+=("$f:extra")
        fi
    done
}
detect_version_files

read_current_version() {
    local file type ver
    for entry in "${VERSION_FILES[@]:-}"; do
        file="${entry%%:*}"; type="${entry##*:}"
        case "$type" in
            json)       ver=$(grep '"version"' "$file" | head -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+[^"]*' || true) ;;
            toml)       ver=$(grep -E '^\s*version\s*=' "$file" | head -1 | grep -oE '"[^"]+"' | tr -d '"' || true) ;;
            setup_py)   ver=$(grep -E 'version\s*=' "$file" | head -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+[^"'"'"']*' || true) ;;
            ini)        ver=$(grep -E '^version\s*=' "$file" | head -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+.*' || true) ;;
            py_appver)  ver=$(grep 'APP_VERSION\s*=' "$file" | head -1 | grep -oE '"[^"]+"' | tr -d '"' || true) ;;
            py_dunder)  ver=$(grep '__version__\s*=' "$file" | head -1 | grep -oE '"[^"]+"' | tr -d '"' || true) ;;
            qt_ver)     ver=$(grep 'setApplicationVersion' "$file" | head -1 | grep -oE '"[^"]+"' | tr -d '"' || true) ;;
            plain)      ver=$(cat "$file" | tr -d '[:space:]' || true) ;;
            badge)      ver=$(grep -oE 'badge/Version-[^-]+-orange' "$file" | head -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+[^-]*' || true) ;;
        esac
        if [[ -n "${ver:-}" ]]; then
            echo "$ver"
            return
        fi
    done
    echo ""
}

update_version_files() {
    local old_ver="$1" new_ver="$2"
    local file type updated=()
    for entry in "${VERSION_FILES[@]:-}"; do
        file="${entry%%:*}"; type="${entry##*:}"
        case "$type" in
            json)       sed -i "s/\"version\"\s*:\s*\"${old_ver}\"/\"version\": \"${new_ver}\"/g" "$file" && updated+=("$file") || true ;;
            toml)       sed -i "s/^version\s*=\s*\"${old_ver}\"/version = \"${new_ver}\"/" "$file" && updated+=("$file") || true ;;
            setup_py)   sed -i "s/version\s*=\s*['\"][^'\"]*['\"]/version=\"${new_ver}\"/g" "$file" && updated+=("$file") || true ;;
            ini)        sed -i "s/^version\s*=.*/version = ${new_ver}/" "$file" && updated+=("$file") || true ;;
            py_appver)  sed -i "s/APP_VERSION\s*=\s*\"[^\"]*\"/APP_VERSION = \"${new_ver}\"/g" "$file" && updated+=("$file") || true ;;
            py_dunder)  sed -i "s/__version__\s*=\s*\"[^\"]*\"/__version__ = \"${new_ver}\"/g" "$file" && updated+=("$file") || true ;;
            qt_ver)     sed -i "s/setApplicationVersion(\"[^\"]*\")/setApplicationVersion(\"${new_ver}\")/g" "$file" && updated+=("$file") || true ;;
            plain)      echo "$new_ver" > "$file" && updated+=("$file") || true ;;
            badge)      sed -i "s/badge\/Version-[a-zA-Z0-9.]*-orange/badge\/Version-${new_ver}-orange/g" "$file" && updated+=("$file") || true ;;
            extra)      sed -i "s/${old_ver//./\\.}/${new_ver}/g" "$file" && updated+=("$file") || true ;;
        esac
    done
    echo "${updated[*]:-}"
}

# ── Genera note di rilascio ───────────────────────────────────────────────────
generate_release_notes() {
    local commits="$1" version="$2" lang="$3"
    local prompt

    if [[ "$lang" == "it" ]]; then
        prompt="Trasforma i seguenti commit message git in note di rilascio professionali per ${PROJECT_NAME} v${version}.

Istruzioni:
- Scrivi in italiano
- Raggruppa per categoria con questi titoli (includi solo quelle presenti):
  ## 🆕 Nuove funzionalità
  ## ⚡ Miglioramenti
  ## 🐛 Correzioni di bug
  ## 🔧 Manutenzione
- Ogni voce come elenco puntato con •
- Linguaggio chiaro, orientato all'utente finale
- Ometti commit di tipo 'chore: release', 'chore: bump', 'chore: version'
- Massimo 2 righe per voce, inizia direttamente con le categorie

Commit:
${commits}"
    else
        prompt="Transform the following git commit messages into professional release notes for ${PROJECT_NAME} v${version}.

Instructions:
- Write in English
- Group by category using these headings (include only those present):
  ## 🆕 New Features
  ## ⚡ Improvements
  ## 🐛 Bug Fixes
  ## 🔧 Maintenance
- Each entry as a bullet point with •
- Clear language aimed at end users
- Omit commits of type 'chore: release', 'chore: bump', 'chore: version'
- Maximum 2 lines per entry, start directly with the categories

Commits:
${commits}"
    fi

    if command -v curl &>/dev/null && command -v jq &>/dev/null && [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
        info "Generazione note con Claude AI..." >&2
        local payload result
        payload=$(jq -n --arg txt "$prompt" '{
            model: "claude-haiku-4-5-20251001",
            max_tokens: 2048,
            messages: [{"role": "user", "content": $txt}]
        }')
        result=$(curl -sf --max-time 30 -X POST "https://api.anthropic.com/v1/messages" \
            -H "x-api-key: $ANTHROPIC_API_KEY" \
            -H "anthropic-version: 2023-06-01" \
            -H "content-type: application/json" \
            -d "$payload" | jq -r '.content[0].text' 2>/dev/null || true)
            
        if [[ -n "$result" && "$result" != "null" ]]; then
            ok "Note generate con AI." >&2
            echo "$result"; return 0
        fi
        warn "Claude API non raggiungibile o chiave non valida; uso formattazione base."
    else
        warn "AI non disponibile (curl/jq mancanti o ANTHROPIC_API_KEY non impostata); uso formattazione base."
    fi

    # Fallback: raggruppa per tipo conventional commit
    local feat="" fix="" perf="" other=""
    while IFS= read -r subj; do
        local clean
        clean=$(printf '%s' "$subj" | sed -E 's/^[a-z]+(\([^)]+\))?: //')
        if   [[ "$subj" =~ ^feat  ]]; then feat+="• $clean"$'\n'
        elif [[ "$subj" =~ ^fix   ]]; then fix+="• $clean"$'\n'
        elif [[ "$subj" =~ ^perf  ]]; then perf+="• $clean"$'\n'
        else                               other+="• $clean"$'\n'
        fi
    done < <(
        echo "$commits" \
            | awk '/^---commit---/ { if (s != "") print s; s = ""; next }
                   /^[[:space:]]*$/ { next }
                   s == ""          { s = $0 }
                   END              { if (s != "") print s }' \
            | grep -Eiv "^chore: (release|bump|version)" || true
    )
    
    local out=""
    if [[ "$lang" == "it" ]]; then
        if [[ -n "$feat" ]]; then out+=$'## 🆕 Nuove funzionalità\n'"$feat"$'\n'; fi
        if [[ -n "$perf" ]]; then out+=$'## ⚡ Miglioramenti\n'"$perf"$'\n'; fi
        if [[ -n "$fix" ]]; then out+=$'## 🐛 Correzioni di bug\n'"$fix"$'\n'; fi
        if [[ -n "$other" ]]; then out+=$'## 🔧 Manutenzione\n'"$other"$'\n'; fi
    else
        if [[ -n "$feat" ]]; then out+=$'## 🆕 New Features\n'"$feat"$'\n'; fi
        if [[ -n "$perf" ]]; then out+=$'## ⚡ Improvements\n'"$perf"$'\n'; fi
        if [[ -n "$fix" ]]; then out+=$'## 🐛 Bug Fixes\n'"$fix"$'\n'; fi
        if [[ -n "$other" ]]; then out+=$'## 🔧 Maintenance\n'"$other"$'\n'; fi
    fi
    echo "${out%$'\n'}"
}

# ── Pubblica release sulla piattaforma rilevata ───────────────────────────────
publish_release() {
    local tag="$1" version="$2" notes_file="$3"
    case "$PLATFORM" in
        github)
            if command -v gh &>/dev/null; then
                gh release create "$tag" \
                    --title "${PROJECT_NAME} ${version}" \
                    --notes-file "$notes_file"
                ok "Release pubblicata su GitHub."
            else
                warn "GitHub CLI (gh) non trovata. Pubblica manualmente su:"
                echo "  https://github.com/$(git remote get-url origin 2>/dev/null | sed 's|.*github.com[:/]||;s|\.git$||' || true)/releases"
                _print_notes_fallback "$version" "$notes_file"
            fi ;;
        gitlab)
            if command -v glab &>/dev/null; then
                glab release create "$tag" \
                    --name "${PROJECT_NAME} ${version}" \
                    --notes-file "$notes_file"
                ok "Release pubblicata su GitLab."
            else
                warn "GitLab CLI (glab) non trovata. Pubblica manualmente su GitLab → Releases."
                _print_notes_fallback "$version" "$notes_file"
            fi ;;
        none)
            warn "Nessun remote rilevato; il tag e' solo locale."
            _print_notes_fallback "$version" "$notes_file" ;;
    esac
}

_print_notes_fallback() {
    local version="$1" notes_file="$2"
    echo ""
    echo "── Note di rilascio ──────────────────────────────────"
    echo "## ${PROJECT_NAME} ${version}"
    echo ""
    cat "$notes_file"
    echo "──────────────────────────────────────────────────────"
}

# ═════════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${BOLD}=== Release: ${PROJECT_NAME} === branch: ${MAIN_BRANCH} === ${PLATFORM} ===${RESET}"
if $DRY_RUN; then
    echo -e "${YELLOW}[DRY RUN — nessuna modifica verra' applicata]${RESET}"
fi
echo ""

# Mostra file di versione rilevati
if [[ ${#VERSION_FILES[@]} -gt 0 ]]; then
    info "File di versione rilevati: ${VERSION_FILES[*]}"
else
    warn "Nessun file di versione rilevato automaticamente."
    info "Aggiungi file specifici in .versiona.conf con EXTRA_UPDATE_FILES=(\"file\")"
fi

# Versione corrente
CURRENT_VERSION=$(read_current_version)
LATEST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "")

if [[ -n "$CURRENT_VERSION" ]]; then
    info "Versione corrente nei sorgenti: ${BOLD}${CURRENT_VERSION}${RESET}"
elif [[ -n "$LATEST_TAG" ]]; then
    CURRENT_VERSION="${LATEST_TAG#v}"
    info "Versione dall'ultimo tag: ${BOLD}${LATEST_TAG}${RESET}"
fi

# ── Raccolta commit preliminare ──────────────────────────────────────────────
info "Analisi dei commit dal tag ${BOLD}${LATEST_TAG:-inizio}${RESET} a HEAD..."
if [[ -z "$LATEST_TAG" ]]; then
    RAW_COMMITS=$(git log --pretty=tformat:"---commit---%n%B" --no-merges || true)
else
    RAW_COMMITS=$(git log "${LATEST_TAG}..HEAD" --pretty=tformat:"---commit---%n%B" --no-merges || true)
fi

FILTERED_COMMITS=$(echo "$RAW_COMMITS" | grep -Eiv "^chore: (release|bump|version) " || true)

# ── Versione suggerita tramite Semantic Versioning ──────────────────────────
if [[ -n "$CURRENT_VERSION" ]]; then
    IFS='.' read -r MAJOR MINOR PATCH <<< "${CURRENT_VERSION%%[-+]*}"
    MAJOR=${MAJOR:-0}; MINOR=${MINOR:-0}; PATCH=${PATCH:-0}

    # Aumentiamo sempre l'ultima cifra (PATCH) di 1, ignorando il tipo di commit
        PATCH=$(( PATCH + 1 ))
    
        # Logica di riporto (rollover): se PATCH o MINOR arrivano a 10, scalano al successivo
        if [[ $PATCH -gt 9 ]]; then
            PATCH=0
            MINOR=$(( MINOR + 1 ))
        fi
        
        if [[ $MINOR -gt 9 ]]; then
            MINOR=0
            MAJOR=$(( MAJOR + 1 ))
        fi

    SUGGESTED_VERSION="${MAJOR}.${MINOR}.${PATCH}"
else
    SUGGESTED_VERSION="0.1.0"
fi

sep

read -rp "$(echo -e "${BOLD}Nuova versione${RESET} [$SUGGESTED_VERSION]: ")" VERSION
VERSION=${VERSION:-$SUGGESTED_VERSION}
TAG_VERSION="v$VERSION"

# ── Generazione note di rilascio ─────────────────────────────────────────────
if [[ -z "${FILTERED_COMMITS// }" ]]; then
    CHANGELOG="• nessun commit trovato"
else
    CHANGELOG=$(generate_release_notes "$FILTERED_COMMITS" "$VERSION" "$LANG_NOTES")
fi

# Anteprima e Modifica (Aggiornato)
while true; do
    echo ""
    sep
    echo -e "${BOLD}Note di rilascio per ${PROJECT_NAME} v${VERSION}:${RESET}"
    sep
    echo ""
    echo "$CHANGELOG"
    echo ""
    sep
    echo ""
    
    read -rp "$(echo -e "Continuare con la release ${BOLD}$VERSION${RESET}? [s(i)/N(o)/e(dita note)] ")" CONFIRM
    CONFIRM=${CONFIRM:-N}
    
    if [[ "${CONFIRM,,}" == "n" ]]; then
        warn "Release annullata."
        exit 0
    elif [[ "${CONFIRM,,}" == "e" ]]; then
        TMP_EDIT=$(mktemp /tmp/versiona_edit_XXXX.md)
        echo "$CHANGELOG" > "$TMP_EDIT"
        ${EDITOR:-nano} "$TMP_EDIT"
        CHANGELOG=$(cat "$TMP_EDIT")
        rm -f "$TMP_EDIT"
        info "Note di rilascio modificate correttamente."
        # Il ciclo ripartirà mostrando l'anteprima aggiornata
    elif [[ "${CONFIRM,,}" == "s" ]]; then
        break
    else
        echo -e "${YELLOW}Scelta non valida. Inserisci s (sì), n (no) o e (edita).${RESET}"
    fi
done

if $DRY_RUN; then
    ok "[DRY RUN] Nessuna modifica applicata. Uscita."
    exit 0
fi

# Aggiorna sorgenti
echo ""
info "Aggiornamento file alla versione $VERSION..."
UPDATED=$(update_version_files "${CURRENT_VERSION:-0.0.0}" "$VERSION")
if [[ -n "${UPDATED// }" ]]; then
    ok "File aggiornati:"
    echo "$UPDATED"
else
    warn "Nessun file aggiornato (pattern non trovati); continuo comunque."
fi

# Aggiorna windowsbuild/version_info.txt (metadati PE Windows)
VERSION_INFO_FILE="windowsbuild/version_info.txt"
if [[ -f "$VERSION_INFO_FILE" ]]; then
    info "Aggiorno ${VERSION_INFO_FILE}..."
    python3 - <<PYEOF
import re

version_str = "${VERSION}"
parts = version_str.split(".")
while len(parts) < 4:
    parts.append("0")
ver_tuple = "({})".format(", ".join(parts))

with open("${VERSION_INFO_FILE}", "r", encoding="utf-8") as fh:
    content = fh.read()

content = re.sub(r"filevers=\([\d, ]+\)", f"filevers={ver_tuple}", content)
content = re.sub(r"prodvers=\([\d, ]+\)", f"prodvers={ver_tuple}", content)
content = re.sub(r"'FileVersion',\s+'[\d.]+'", f"'FileVersion', '{version_str}.0'", content)
content = re.sub(r"'ProductVersion',\s+'[\d.]+'", f"'ProductVersion', '{version_str}'", content)

with open("${VERSION_INFO_FILE}", "w", encoding="utf-8") as fh:
    fh.write(content)
PYEOF
    ok "${VERSION_INFO_FILE} aggiornato a v${VERSION}."
    UPDATED="${UPDATED} ${VERSION_INFO_FILE}"
else
    warn "${VERSION_INFO_FILE} non trovato; salta aggiornamento metadati PE."
fi

# Commit di release
info "Creazione commit di release..."
if [[ -n "${UPDATED// }" ]]; then
    for f in $UPDATED; do
        git add "$f" 2>/dev/null || true
    done
fi
git commit -m "chore: release $VERSION" --allow-empty
ok "Commit creato."

# Tag annotato
info "Creazione tag $TAG_VERSION..."
git tag -a "$TAG_VERSION" -m "$(printf '%s %s\n\n%s' "$PROJECT_NAME" "$VERSION" "$CHANGELOG")"
ok "Tag $TAG_VERSION creato."

# Push
info "Push di ${MAIN_BRANCH} e tag..."
git push origin "$MAIN_BRANCH"
git push origin "$TAG_VERSION"
ok "Push completato."

# Pubblicazione release
echo ""
info "Pubblicazione release..."
NOTES_FILE=$(mktemp /tmp/release_notes_XXXX.md)
printf '## %s %s\n\n%s\n' "$PROJECT_NAME" "$VERSION" "$CHANGELOG" > "$NOTES_FILE"
publish_release "$TAG_VERSION" "$VERSION" "$NOTES_FILE"
rm -f "$NOTES_FILE"

# ── Build AppImage locale + upload alla release ───────────────────────────────
# La GitHub Action .github/workflows/release.yml builda l'AppImage in automatico
# dopo il release:published. Di default la build locale è saltata; per forzarla
# in locale (es. connessione assente) usa BUILD_LOCAL_APPIMAGE=1.
APPIMAGE_BUILD_SCRIPT="packaging/appimage/build-appimage.sh"
if [[ -f "$APPIMAGE_BUILD_SCRIPT" && "${BUILD_LOCAL_APPIMAGE:-0}" == "1" ]]; then
    echo ""
    sep
    info "Avvio build AppImage locale..."
    bash "$APPIMAGE_BUILD_SCRIPT"
    # Individua il file AppImage prodotto
    APPIMAGE_FILE=$(ls dist/NotePadPQ-${VERSION}-*.AppImage 2>/dev/null | head -1 || true)
    if [[ -z "$APPIMAGE_FILE" ]]; then
        warn "AppImage non trovata in dist/. Upload saltato."
    else
        ok "AppImage prodotta: ${APPIMAGE_FILE} ($(du -sh "${APPIMAGE_FILE}" | cut -f1))"
        # Upload alla release GitHub tramite gh CLI (se disponibile)
        if command -v gh >/dev/null 2>&1; then
            _fsize=$(du -sh "${APPIMAGE_FILE}" | cut -f1)
            info "Caricamento ${APPIMAGE_FILE} nella release ${TAG_VERSION} (${_fsize})..."
            _upload_ok=false
            if command -v curl >/dev/null 2>&1; then
                _slug=$(git remote get-url origin 2>/dev/null | sed 's|.*github.com[:/]||;s|\.git$||')
                _rel_id=$(gh api "repos/${_slug}/releases/tags/${TAG_VERSION}" --jq '.id' 2>/dev/null || true)
                _token=$(gh auth token 2>/dev/null || true)
                _fname=$(basename "${APPIMAGE_FILE}")
                if [[ -n "$_rel_id" && -n "$_token" ]]; then
                    # Clobber: rimuovi asset preesistente con lo stesso nome
                    _aid=$(gh api "repos/${_slug}/releases/${_rel_id}/assets" \
                        --jq ".[] | select(.name==\"${_fname}\") | .id" 2>/dev/null || true)
                    [[ -n "$_aid" ]] && \
                        gh api --method DELETE "repos/${_slug}/releases/assets/${_aid}" >/dev/null 2>&1 || true
                    read -rp "$(echo -e "Velocità upload: [L]ento 500 KB/s o [V]eloce (max)? [L/v] ")" _speed_choice
                    _speed_choice=${_speed_choice:-L}
                    if [[ "${_speed_choice,,}" == "v" ]]; then
                        _rate_opt=""
                        info "Upload alla massima velocità."
                    else
                        _rate_opt="--limit-rate 500k"
                        info "Upload limitato a 500 KB/s."
                    fi
                    _up_url="https://uploads.github.com/repos/${_slug}/releases/${_rel_id}/assets?name=${_fname}"
                    _http=$(curl -# ${_rate_opt} -X POST \
                        -H "Authorization: token ${_token}" \
                        -H "Content-Type: application/octet-stream" \
                        "${_up_url}" --data-binary @"${APPIMAGE_FILE}" \
                        -w "%{http_code}" -o /dev/null)
                    [[ "$_http" == "201" ]] && _upload_ok=true
                fi
            fi
            if ! $_upload_ok; then
                gh release upload "${TAG_VERSION}" "${APPIMAGE_FILE}" --clobber && \
                    _upload_ok=true || true
            fi
            $_upload_ok && ok "AppImage caricata nella release ${TAG_VERSION}." || \
                warn "Upload fallito. Puoi caricarla manualmente dalla pagina release."
        else
            warn "gh CLI non trovato. Carica manualmente l'AppImage nella release:"
            echo "  ${APPIMAGE_FILE}"
            echo "  → https://github.com/$(git remote get-url origin 2>/dev/null | sed 's|.*github.com[:/]||;s|\.git$||')/releases/tag/${TAG_VERSION}"
        fi
    fi
elif [[ -f "$APPIMAGE_BUILD_SCRIPT" ]]; then
    info "Build AppImage locale saltata. GitHub Actions la produrrà e caricherà automaticamente."
fi

# ── Build Windows opzionale ───────────────────────────────────────────────────
BUILD_SCRIPT="windowsbuild/build.sh"
if [[ -f "$BUILD_SCRIPT" ]]; then
    echo ""
    sep
    read -rp "$(echo -e "Avviare la ${BOLD}build Windows${RESET} locale ora? [s/N] ")" DO_BUILD
    DO_BUILD=${DO_BUILD:-N}
    if [[ "${DO_BUILD,,}" == "s" ]]; then
        echo ""
        read -rp "$(echo -e "Quale variante? [${BOLD}full${RESET}/both/lite] ")" BUILD_VARIANT
        BUILD_VARIANT=${BUILD_VARIANT:-full}
        info "Avvio build Windows (${BUILD_VARIANT})..."
        bash "$BUILD_SCRIPT" "$BUILD_VARIANT"
    else
        info "Build Windows saltata. Per compilare manualmente:"
        echo "  bash windowsbuild/build.sh        # entrambe le versioni"
        echo "  bash windowsbuild/build.sh full   # solo Full"
        echo "  bash windowsbuild/build.sh lite   # solo Lite"
    fi
fi

echo ""
echo -e "${GREEN}${BOLD}=== ✔  ${PROJECT_NAME} ${VERSION} rilasciato con successo! ===${RESET}"
echo ""

# ── Pulizia artefatti di build ────────────────────────────────────────────────
sep
info "Pulizia artefatti di build..."
rm -rf "$REPO_ROOT/dist/" "$REPO_ROOT/build/" "$REPO_ROOT/.venv-build/" "$REPO_ROOT/__pycache__/" "$REPO_ROOT/.pytest_cache/"
ok "Pulizia completata (dist/, build/, .venv-build/, __pycache__/, .pytest_cache/)."
echo ""