#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
#  Nx-Citadel — Start (development mode, runs from this directory)
#  Usage: bash StartCitadel.sh
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="${SCRIPT_DIR}/.citadel.pid"
LOG_FILE="${SCRIPT_DIR}/logs/citadel.log"
VENV="${SCRIPT_DIR}/.venv"
PORT=8000

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

ok()   { echo -e "  ${GREEN}✔${RESET}  $1"; }
info() { echo -e "  ${CYAN}→${RESET}  $1"; }
warn() { echo -e "  ${YELLOW}⚠${RESET}  $1"; }
die()  { echo -e "\n${RED}${BOLD}ERROR:${RESET} $1\n"; exit 1; }

echo ""
echo -e "${CYAN}${BOLD}Nx-Citadel — Starting (dev mode)${RESET}"
echo ""

# ── Check for existing running instance ──────────────────────────────────────
if [[ -f "$PID_FILE" ]]; then
  OLD_PID=$(cat "$PID_FILE")
  if kill -0 "$OLD_PID" 2>/dev/null; then
    warn "Citadel is already running  (PID: ${OLD_PID})"
    echo ""
    HOST_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
    info "Web interface is available at:"
    info "  http://localhost:${PORT}"
    [[ -n "$HOST_IP" ]] && info "  http://${HOST_IP}:${PORT}  (network)"
    echo ""
    info "No action taken. To restart: bash StopCitadel.sh && bash StartCitadel.sh"
    echo ""
    exit 0
  else
    rm -f "$PID_FILE"
  fi
fi

# ── Verify Python virtual environment ────────────────────────────────────────
[[ -f "${VENV}/bin/python" ]] \
  || die "Virtual environment not found at ${VENV}\n  Create it first:\n    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"

# ── Ensure log directory exists ───────────────────────────────────────────────
mkdir -p "${SCRIPT_DIR}/logs"

info "Working directory : ${SCRIPT_DIR}"
info "Python            : ${VENV}/bin/python"
info "Log file          : ${LOG_FILE}"
info "Starting server on port ${PORT}…"
echo ""

# ── Launch in background ──────────────────────────────────────────────────────
cd "${SCRIPT_DIR}"
nohup "${VENV}/bin/python" run.py >> "${LOG_FILE}" 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"

# ── Wait and confirm running ──────────────────────────────────────────────────
echo -n "  Waiting for server to come up"
for i in {1..15}; do
  sleep 1
  echo -n "."
  if ! kill -0 "$NEW_PID" 2>/dev/null; then
    echo ""
    echo ""
    die "Process exited immediately.\n\n  Check the logs:\n    tail -50 ${LOG_FILE}\n\n  Common causes:\n    • Port ${PORT} already in use\n    • Missing Python dependency (run: .venv/bin/pip install -r requirements.txt)\n    • Syntax error in application code"
  fi
  if curl -sf "http://localhost:${PORT}" -o /dev/null 2>/dev/null \
     || curl -sf "http://localhost:${PORT}/health" -o /dev/null 2>/dev/null; then
    echo ""
    break
  fi
done
echo ""

if ! kill -0 "$NEW_PID" 2>/dev/null; then
  rm -f "$PID_FILE"
  die "Server failed to start. Check logs: tail -50 ${LOG_FILE}"
fi

ok "Citadel is running  (PID: ${NEW_PID})"

HOST_IP=$(hostname -I 2>/dev/null | awk '{print $1}')

echo ""
echo -e "${GREEN}${BOLD}══════════════════════════════════════════════${RESET}"
echo -e "${GREEN}${BOLD}  Nx-Citadel is running  [dev mode]${RESET}"
echo -e "${GREEN}${BOLD}══════════════════════════════════════════════${RESET}"
echo ""
info "Web interface:"
info "  http://localhost:${PORT}"
[[ -n "$HOST_IP" ]] && info "  http://${HOST_IP}:${PORT}  (network)"
echo ""
info "Useful commands:"
info "  View logs   : tail -f ${LOG_FILE}"
info "  Stop        : bash StopCitadel.sh"
echo ""
