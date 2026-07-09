#!/bin/bash

# --- Configuration ---
LOG_FILE="/tmp/public_share_$(date +%Y%m%d_%H%M%S).log"
OUTPUT_DIR="$(pwd)/out/journals"
START_PORT=8787
TUNNEL_HOST="localhost.run"

# --- Couleurs ANSI ---
RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[1;33m'
BLUE=$'\033[0;34m'
CYAN=$'\033[0;36m'
BOLD=$'\033[1m'
NC=$'\033[0m'

# --- Fonctions de Log ---
log_debug() { echo -e "${CYAN}[DEBUG] $(date +%H:%M:%S) ${1}${NC}" >> "${LOG_FILE}"; }
log_info() { echo -e "${BLUE}[INFO] $(date +%H:%M:%S) ${1}${NC}" | tee -a "${LOG_FILE}"; }
log_warn() { echo -e "${YELLOW}[WARN] $(date +%H:%M:%S) ${1}${NC}" | tee -a "${LOG_FILE}"; }
log_error() { echo -e "${RED}[ERROR] $(date +%H:%M:%S) ${1}${NC}" | tee -a "${LOG_FILE}"; }

# --- Variables Globales ---
HTTP_SERVER_PID=""
SSH_TUNNEL_PID=""
TUNNEL_URL=""
HTML_FILE=""

# --- Fonction de Nettoyage ---
cleanup() {
    log_info "Nettoyage des processus..."
    if [ -n "${HTTP_SERVER_PID}" ]; then
        log_debug "Tentative d'arrêt du serveur HTTP (PID: ${HTTP_SERVER_PID})"
        kill -SIGTERM "${HTTP_SERVER_PID}" 2>/dev/null
        wait "${HTTP_SERVER_PID}" 2>/dev/null
        if kill -0 "${HTTP_SERVER_PID}" 2>/dev/null; then
            log_warn "Le serveur HTTP (PID: ${HTTP_SERVER_PID}) n'a pas répondu, le tuant..."
            kill -SIGKILL "${HTTP_SERVER_PID}" 2>/dev/null
        fi
        log_info "Serveur HTTP arrêté."
    fi

    if [ -n "${SSH_TUNNEL_PID}" ]; then
        log_debug "Tentative d'arrêt du tunnel SSH (PID: ${SSH_TUNNEL_PID})"
        kill -SIGTERM "${SSH_TUNNEL_PID}" 2>/dev/null
        wait "${SSH_TUNNEL_PID}" 2>/dev/null
        if kill -0 "${SSH_TUNNEL_PID}" 2>/dev/null; then
            log_warn "Le tunnel SSH (PID: ${SSH_TUNNEL_PID}) n'a pas répondu, le tuant..."
            kill -SIGKILL "${SSH_TUNNEL_PID}" 2>/dev/null
        fi
        log_info "Tunnel SSH arrêté."
    fi
    log_info "Nettoyage terminé."
    exit 0
}

# --- Piège pour les signaux (Ctrl+C) ---
trap cleanup SIGINT SIGTERM

# --- Vérifier la disponibilité d'une commande ---
check_command() {
    command -v "$1" >/dev/null 2>&1
}

# --- Installer les dépendances ---
install_dependencies() {
    log_info "Vérification et installation des dépendances..."

    if ! check_command "python3"; then
        log_error "python3 n'est pas installé. Veuillez l'installer."
        return 1
    fi

    if ! check_command "ssh"; then
        log_error "ssh n'est pas installé. Veuillez l'installer."
        return 1
    fi

    # Vérifier les outils de presse-papiers
    if [[ "$(uname)" == "Darwin" ]]; then
        if ! check_command "pbcopy"; then
            log_warn "pbcopy non trouvé. La copie dans le presse-papiers pourrait ne pas fonctionner."
        fi
    elif [[ "$(uname)" == "Linux" ]]; then
        if ! check_command "xclip" && ! check_command "xsel"; then
            log_warn "xclip ou xsel non trouvé. La copie dans le presse-papiers pourrait ne pas fonctionner. Installez 'xclip' ou 'xsel'."
        fi
    fi
    return 0
}

# --- Trouver un port disponible ---
find_available_port() {
    local port="$1"
    while true; do
        if ! netstat -tuln | grep -q ":${port}\b"; then
            echo "${port}"
            return 0
        fi
        ((port++))
    done
}

# --- Copier dans le presse-papiers ---
copy_to_clipboard() {
    local text="$1"
    if [[ "$(uname)" == "Darwin" ]]; then
        echo "${text}" | pbcopy
        log_info "Lien copié dans le presse-papiers (macOS)."
    elif [[ "$(uname)" == "Linux" ]]; then
        if check_command "xclip"; then
            echo "${text}" | xclip -selection clipboard
            log_info "Lien copié dans le presse-papiers (Linux - xclip)."
        elif check_command "xsel"; then
            echo "${text}" | xsel --clipboard --input
            log_info "Lien copié dans le presse-papiers (Linux - xsel)."
        else
            log_warn "Aucun outil de presse-papiers trouvé pour Linux."
            return 1
        fi
    else
        log_warn "Copie dans le presse-papiers non supportée sur ce système."
        return 1
    fi
    return 0
}

# --- Ouvrir le navigateur ---
open_browser() {
    local url="$1"
    if check_command "xdg-open"; then
        xdg-open "${url}" >/dev/null 2>&1 &
    elif check_command "open"; then # macOS
        open "${url}" >/dev/null 2>&1 &
    elif check_command "sensible-browser"; then
        sensible-browser "${url}" >/dev/null 2>&1 &
    else
        log_warn "Impossible d'ouvrir le navigateur automatiquement. Veuillez ouvrir: ${url}"
        return 1
    fi
    log_info "Ouverture du navigateur avec l'URL: ${url}"
    return 0
}

# --- Fonction principale ---
main() {
    log_info "Démarrage du script de partage public."
    log_info "Fichier de log: ${LOG_FILE}"

    if ! install_dependencies; then
        log_error "Échec de la vérification/installation des dépendances. Sortie."
        exit 1
    fi

    if [ ! -d "${OUTPUT_DIR}" ]; then
        log_error "Le répertoire '${OUTPUT_DIR}' est introuvable. Veuillez vous assurer qu'il existe."
        exit 1
    fi

    # Trouver le dernier fichier HTML
    HTML_FILE=$(find "${OUTPUT_DIR}" -maxdepth 1 -name "secjournal_*.html" | sort -r | head -n 1)
    if [ -z "${HTML_FILE}" ]; then
        log_error "Aucun fichier HTML 'secjournal_*.html' trouvé dans '${OUTPUT_DIR}'."
        exit 1
    fi
    log_info "Fichier HTML à partager: $(basename "${HTML_FILE}")"

    # --- Démarrer le serveur HTTP Python pour un seul fichier ---
    PORT=$(find_available_port "${START_PORT}")
    log_info "Démarrage du serveur HTTP Python sur le port ${PORT} pour le fichier '$(basename "${HTML_FILE}")'..."
    python3 single_file_server.py "${PORT}" "${HTML_FILE}" >/dev/null 2>&1 &
    HTTP_SERVER_PID=$!
    log_debug "Serveur HTTP démarré avec PID: ${HTTP_SERVER_PID}"

    # Attendre que le serveur soit prêt
    for i in $(seq 1 20); do
        if curl -s "http://127.0.0.1:${PORT}" >/dev/null; then
            log_info "Serveur HTTP démarré avec succès sur le port ${PORT}."
            break
        fi
        log_debug "Attente du serveur HTTP... (${i}/20)"
        sleep 0.5
        if [ "$i" -eq 20 ]; then
            log_error "Le serveur HTTP n'a pas démarré à temps."
            cleanup
        fi
    done

    # --- Démarrer le tunnel SSH via localhost.run ---
    log_info "Démarrage du tunnel SSH via ${TUNNEL_HOST} pour http://127.0.0.1:${PORT}..."
    # Utiliser un fichier temporaire pour capturer la sortie de stderr de ssh
    SSH_LOG_TEMP=$(mktemp)
    ssh -R 80:localhost:"${PORT}" "${TUNNEL_HOST}" -N 2>"${SSH_LOG_TEMP}" &
    SSH_TUNNEL_PID=$!
    log_debug "Tunnel SSH démarré avec PID: ${SSH_TUNNEL_PID}"

    # Attendre l'URL du tunnel
    log_info "Attente de l'établissement du tunnel SSH..."
    MAX_WAIT=45
    ELAPSED_TIME=0
    while [ -z "${TUNNEL_URL}" ] && [ "${ELAPSED_TIME}" -lt "${MAX_WAIT}" ]; do
        # localhost.run imprime l'URL sur stderr
        TUNNEL_URL=$(grep -oP 'https?://[^\s]+' "${SSH_LOG_TEMP}" | head -n 1)
        if [ -n "${TUNNEL_URL}" ]; then
            log_info "Tunnel SSH établi. URL: ${TUNNEL_URL}"
            break
        fi
        log_debug "En attente de l'URL du tunnel... (${ELAPSED_TIME}/${MAX_WAIT})"
        sleep 1
        ((ELAPSED_TIME++))
    done
    rm "${SSH_LOG_TEMP}" # Nettoyer le fichier temporaire

    if [ -z "${TUNNEL_URL}" ]; then
        log_error "Impossible d'obtenir l'URL du tunnel SSH après ${MAX_WAIT} secondes."
        cleanup
    fi

    # --- Construire l'URL complète et vérifier l'accès ---
    FULL_URL="${TUNNEL_URL}/$(basename "${HTML_FILE}")"
    log_info "Vérification de l'accès au fichier via le tunnel: ${FULL_URL}"
    for i in $(seq 1 15); do
        if curl -s -f "${FULL_URL}" >/dev/null; then
            log_info "Fichier accessible via le tunnel !"
            break
        fi
        log_debug "Attente de l'accès au fichier via le tunnel... (${i}/15)"
        sleep 2
        if [ "$i" -eq 15 ]; then
            log_error "Impossible d'accéder au fichier via le tunnel après plusieurs tentatives."
            cleanup
        fi
    done

    # --- Afficher les informations ---
    echo -e "\n${BOLD}${GREEN}════════════════════════════════════════════════════════━━━━━━${NC}"
    echo -e "${BOLD}${GREEN}✅ Tunnel SSH créé avec succès !${NC}"
    echo -e "${BOLD}${GREEN}════════════════════════════════════════════════════════━━━━━━${NC}"
    echo -e "\n${BOLD}${CYAN}🔗 Lien public :${NC}"
    echo -e "${BOLD}${GREEN}  ${FULL_URL}${NC}"
    echo -e "\n${BOLD}${CYAN}📋 Copie du lien dans le presse-papiers...${NC}"
    copy_to_clipboard "${FULL_URL}"

    echo -e "\n${BOLD}${BLUE}🌐 Ouverture du fichier dans le navigateur...${NC}"
    open_browser "${FULL_URL}"

    echo -e "\n${BOLD}${YELLOW}💡 Informations:${NC}"
    echo -e "  • ${GREEN}URL complète:${NC} ${CYAN}${FULL_URL}${NC}"
    echo -e "  • ${GREEN}Fichier:${NC} $(basename "${HTML_FILE}")"
    echo -e "  • ${GREEN}Dossier:${NC} ${OUTPUT_DIR}"
    echo -e "  • ${GREEN}Port local:${NC} ${PORT}"
    echo -e "\n${BOLD}${YELLOW}⏹️  Appuyez sur Ctrl+C pour arrêter le serveur et le tunnel${NC}"
    echo -e "${BOLD}${BLUE}════════════════════════════════════════════════════════━━━━━━${NC}"

    # Garder le script en vie
    while true; do
        sleep 1
    done
}

# --- Exécuter la fonction principale ---
main
